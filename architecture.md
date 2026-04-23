# Architecture — deep dive

This document walks through each of the six boundary layers: what it does,
why it exists, what it fails open vs fail closed on, and what the known
limitations are.

---

## Full pipeline

```
                       customer ticket (any language)
                                │
                                ▼
           ┌─────────────────────────────────────────┐
           │ Layer 1 — High-risk intent              │
           │ Keyword regex (RG / legal / fraud /     │──► escalate
           │ self-harm), multilingual, no LLM call.  │   high_risk_<cat>
           └───────────────────┬─────────────────────┘
                               │ clear
                               ▼
           ┌─────────────────────────────────────────┐
           │ Layer 2 — Out-of-domain classifier      │
           │ LLM zero-shot. Fails OPEN on error —    │──► escalate
           │ downstream layers will still protect.   │   out_of_scope
           └───────────────────┬─────────────────────┘
                               │ in-domain
                               ▼
           ┌─────────────────────────────────────────┐
           │ Layer 3 — Retrieval                     │
           │ multilingual-MiniLM embeddings,         │──► escalate
           │ chunked KB in ChromaDB, cosine sim,     │   low_retrieval
           │ top-k with similarity gate.             │
           └───────────────────┬─────────────────────┘
                               │ sim >= threshold
                               ▼
           ┌─────────────────────────────────────────┐
           │ Layer 4 — Generation                    │
           │ LLM with strict JSON schema:            │──► refused ⇒ escalate
           │ answer / cites / confidence / refused.  │   low_confidence
           │ System prompt: prefer to refuse.        │
           └───────────────────┬─────────────────────┘
                               │ not refused
                               ▼
           ┌─────────────────────────────────────────┐
           │ Layer 5 — Grounding verifier            │
           │ 2nd LLM pass. grounded / partial /      │──► escalate
           │ not_grounded. Fails CLOSED.             │   hallucination
           └───────────────────┬─────────────────────┘
                               │ grounded
                               ▼
           ┌─────────────────────────────────────────┐
           │ Layer 6 — Confidence gate               │──► escalate
           │ self-rated confidence >= threshold?     │   low_confidence
           └───────────────────┬─────────────────────┘
                               │ yes
                               ▼
                     ANSWER + cited sources +
                     confidence + reasoning_trace
```

---

## Layer 1 — High-risk intent

**Files:** `src/classifiers.py::HighRiskClassifier`

A compiled regex per category, multilingual, matched before anything
else runs. No LLM call.

### Categories and pattern intent

| Category  | Intent                                        | Key phrases (EN / RU / PT samples) |
|-----------|-----------------------------------------------|------------------------------------|
| `rg`      | Responsible-gambling distress                 | "can't stop", "lost everything", "не могу остановиться", "vício", "perdi tudo" |
| `legal`   | Regulator / lawsuit / ombudsman threats       | "sue you", "lawyer", "report to MGA", "жаловаться", "скарга", "regulador" |
| `fraud`   | Account-takeover, unauthorised transactions   | "someone hacked", "wasn't me", "stolen", "взломали", "вкрали" |
| `selfharm`| Crisis / suicidal language                    | "end it all", "kill myself", "nothing matters", "немає сенсу жити" |

### Design choices

- **Keyword first, LLM never (for this layer)** — because false
  negatives are dangerous. Keywords are explainable, fast, unit-testable,
  and don't depend on a third-party model's dispositions. You want this
  layer to be boring.
- **Self-harm is checked *first*** — if the same sentence could hit both
  `selfharm` and `rg` (e.g. "I lost everything, nothing matters"), we
  tag it as `selfharm` because the handoff template is more
  safety-focused.
- **Fails OPEN** — if no category matches, we continue to the next
  layer. The cost is picked up later by OOD / retrieval.
- **Category-specific operator message** — the `Decision.message_to_operator`
  carries guidance for the human agent, including which queue to route
  to and which external resources to offer. This is in `pipeline.py`
  `_OPERATOR_MESSAGES`.

### Known limitations

- Pattern-based detection will miss paraphrases the keyword list
  doesn't cover (e.g. metaphorical "drowning"). A real production
  system would augment this with a fine-tuned classifier.
- Multilingual coverage is currently EN / RU / UA / PT. Adding
  languages = adding regex branches; not great but explicit.
- No detection of *sarcasm* ("sure, I'll go tell my lawyer 😂") — these
  are currently tagged as legal threats. Acceptable for a first pass
  because the cost of a false positive is a human agent picking up a
  casual ticket, not a missed safety signal.

---

## Layer 2 — Out-of-domain classifier

**Files:** `src/classifiers.py::OODClassifier`

LLM zero-shot. System prompt lists in-domain topics (account, KYC,
deposits, withdrawals, bonuses, games, payment methods, responsible
gambling, limits, VIP, navigation) and out-of-domain examples (weather,
recipes, trivia, coding help, song lyrics, prompt injection).

### Why this exists separately from retrieval

It's tempting to collapse "out-of-domain" into "low retrieval score" —
and the mock backend mostly does — but they are distinct signals in
production:

- **OOD**: the question isn't about our product at all. Return a polite
  "this isn't something I can help with" and do **not** surface it as a
  KB gap.
- **low_retrieval**: the question is about our product, we just don't
  have an article. Surface this to the KB ops team as a gap to fill.

Conflating them means your "KB gap" dashboard is full of weather
questions.

### Fails OPEN

If the LLM call errors, we return `in_domain=True` and let downstream
layers decide. The reasoning: we'd rather a weather question go through
retrieval (where it will fail to find anything and escalate as
`low_retrieval`) than accidentally block a real support ticket because
the classifier is down.

### Known limitations

- Prompt-injection attempts sometimes succeed against zero-shot
  classifiers. Ticket **D5** ("ignore your previous instructions…") is
  caught by mock keyword cues but would need a hardened prompt to
  survive a determined attacker. In production we'd add input
  sandboxing (delimiter tokens, "the user message is untrusted")
  and a separate prompt-injection detector.
- Latency — every ticket pays one LLM round-trip here. An embeddings-
  based OOD (centroid similarity to KB) would be near-instant at the
  cost of some accuracy; we chose the LLM variant because the KB is
  small (20 articles) so centroid quality would be noisy.

---

## Layer 3 — Retrieval + similarity gate

**Files:** `src/retriever.py`, `src/ingest.py`

- Embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (384 dim, 50+ languages). Chosen specifically because Growe's target
  markets produce tickets in many languages against an English KB.
- Vector DB: ChromaDB with cosine space, persistent directory.
- Chunking: word-based, 180 words per chunk with 30-word overlap. The
  article **title is prepended to every chunk** — a free signal that
  lifts recall on short queries.
- Deduplication: retrieval returns at most one hit per `doc_id`, with
  the max chunk score kept. This stops the generator from seeing the
  same article three times and double-counting evidence.

### Similarity gate

`SIM_THRESHOLD = 0.45` — tuned on the 20-ticket eval. The threshold
trades two kinds of error:

- Too high → valid but ambiguously-worded tickets (e.g. A2 "забыл
  пароль") escalate as `low_retrieval` when they shouldn't.
- Too low → unrelated questions squeak through and get an unhelpful
  answer from the nearest-but-irrelevant article.

At 0.45 we accept that some B-category tickets (notably B5 "Mega
Moolah") leak through because an article mentions "jackpot" in an
unrelated context. The next two layers (generator-refuse and verifier)
are expected to catch those.

### Known limitations

- **No reranker.** The biggest single improvement would be a cross-
  encoder rerank over top-10 before handing to the generator. Addresses
  A4 and A5 directly.
- **Chunk size is word-based, not token-based.** Fine for a 5k-word KB;
  at 100k+ words you want a tokeniser-aware splitter to avoid
  mid-sentence cuts.
- **No hybrid / BM25 fallback.** On a very short query like "kyc eta?"
  lexical match is more reliable than semantic. BM25 + embedding fusion
  would close that gap.

---

## Layer 4 — Structured generation

**Files:** `src/generator.py`

LLM call with a strict JSON schema — `answer`, `cited_sources`,
`confidence` (1-5), `confidence_reason`, `ambiguity_notes`, `refused`.

### Prompt design

The system prompt makes three things very explicit:

1. **Answer ONLY from provided sources.** Never introduce information
   not in the sources.
2. **It is better to refuse than to invent.** `refused=true` is a
   first-class, legitimate outcome, not a failure.
3. **Cite only sources you actually used.** The verifier will check
   this.

The self-rated confidence has an explicit rubric ("5 = exact,
unambiguous; 3 = partial; 1 = should have refused") so the model has a
stable scale rather than inventing one each call.

### Why not tool-use / function-calling?

Providers vary. Groq's chat/completions + `response_format="json_object"`
is the leanest path that works across Groq and (with a tiny prompt
adjustment) Anthropic. Tool-use would be strictly better for
server-validated schema enforcement — worth adopting in production.

### Prompt caching

The Anthropic backend caches the system prompt via `cache_control:
ephemeral`. Every layer above calls the same system prompt for many
tickets in a batch; without caching the token cost scales linearly.

### Known limitations

- `response_format=json_object` does not validate the shape, only that
  the output is JSON. Bad fields silently fall through to `confidence=1,
  refused=True` in the Pydantic normaliser. A stricter contract would
  use tool-use with a JSON-schema enforcement.
- Generation is single-shot. A self-consistency / k-samples approach
  with majority voting on confidence would be a real accuracy win at
  3x–5x cost.

---

## Layer 5 — Grounding verifier

**Files:** `src/verifier.py`

Classic LLM-as-judge. Input: ticket + answer + retrieved sources.
Output: `grounded | partial | not_grounded` + rationale.

### Why it's needed

Even with layer 4's "prefer to refuse" prompt, LLMs drift. Common
failure modes this catches:

- Answer adds a specific timeline / amount / policy not in the sources
- Answer cites a source id that was not in the retrieved set
- Answer extrapolates from the sources into a recommendation

### Fails CLOSED

If the verifier call itself errors, we treat the answer as
`not_grounded` and escalate. An extra escalation is cheap (one human
handoff); a missed hallucination is not.

### Known limitations

- It's an LLM checking an LLM. The same class of biases can sneak past.
  A real production version would rotate models — Groq Llama for
  generation, Anthropic Haiku for verification, or vice versa — so at
  least the two aren't the same model.
- The verifier has no memory of the threshold tuning and may disagree
  with `confidence`. That's fine (two independent signals) but it means
  every "answer" tile is the conjunction `grounded AND confidence>=4`
  — we could in principle send a `partial` + `confidence=5` answer if
  we wanted, but that's a product call.

---

## Layer 6 — Confidence gate

**Files:** `src/pipeline.py`

Simple threshold on the generator's self-rated confidence. Default
`CONFIDENCE_THRESHOLD=4`.

The logic: a model that rates its own answer a 3 ("partial") is
telling us something useful, and we should respect that. An auto-reply
of marginal quality is worse than a thoughtful human reply.

### Known limitation

Models are not always well-calibrated self-raters. In production we'd
compare self-rated confidence to an external calibration — e.g.
temperature-scaled logit margin on the chosen class, or semantic
entropy over k samples — and replace or ensemble.

---

## API contract

`POST /resolve` body:
```json
{ "ticket": "string" }
```

Response — the `Decision` model:
```json
{
  "decision": "answer" | "escalate",
  "escalation_reason": null | "out_of_scope" | "high_risk_rg" |
                       "high_risk_legal" | "high_risk_fraud" |
                       "high_risk_selfharm" | "low_retrieval" |
                       "hallucination" | "low_confidence",
  "answer": "string | null",
  "sources": ["kb_005", ...],
  "confidence": 1-5 | null,
  "reasoning_trace": [
    {"step": "high_risk",  "result": {...}},
    {"step": "ood",        "result": {...}},
    {"step": "retrieval",  "result": {...}},
    {"step": "generation", "result": {...}},
    {"step": "verifier",   "result": {...}},
    {"step": "total_ms",   "result": {"ms": 412}}
  ],
  "message_to_operator": "human-readable handoff guidance"
}
```

`reasoning_trace` is mandatory and complete — it should be sufficient to
reproduce any decision end-to-end.

---

## Performance notes

- Mock backend: p50 ≈ 0 ms, p95 ≈ 12 ms (no network).
- Groq Llama 3.3 70B: ~300-800 ms per ticket end-to-end. OOD + generate
  + verify = 3 LLM calls; high-risk is keyword so free.
- Anthropic Haiku 4.5 with prompt caching on system prompts: ~400-900 ms.

For higher throughput:

- The OOD classifier can be skipped when retrieval top-1 similarity is
  very high (>0.75), saving ~30% of LLM cost. Not implemented —
  deliberate, so the trace is consistent across tickets.
- Generation and verification can be run against different models in
  parallel, but the verifier needs the answer to verify, so full
  parallelisation is only possible with speculative decoding.
