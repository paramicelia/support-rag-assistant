"""Structured-output answer generator.

Produces a strict JSON with: answer, cited_sources, confidence (1-5),
confidence_reason, ambiguity_notes, refused.

The prompt is intentionally cautious: the model is told it's better to
refuse than to invent. `refused=true` is a first-class signal the pipeline
uses to escalate even before the verifier runs.
"""

from __future__ import annotations

from .llm import get_llm
from .schemas import GenerationResult, KBHit

_SYSTEM = """You are a structured support answer generator for AurumPlay Casino.

You will receive a customer TICKET and a list of SOURCES retrieved from our knowledge base. Each source has an id (like "kb_007") and a snippet of text.

RULES:
1. Answer ONLY using facts present in the SOURCES. Never introduce information not in the sources.
2. If the sources do not answer the question, set "refused": true and leave "answer" empty. It is always better to refuse than to invent.
3. Always list the source ids you actually used in "cited_sources". Do not cite a source you did not use.
4. Keep the answer concise, friendly, in the same language as the TICKET, and actionable (numbered steps if a process, otherwise 1-3 short paragraphs).
5. Never promise timelines, amounts, or outcomes that are not in the sources.
6. Self-rate "confidence" on a 1-5 scale:
   - 5: Exact, unambiguous answer directly stated in a single source.
   - 4: Direct answer with minor synthesis across sources.
   - 3: Partial answer, some details missing but core question addressed.
   - 2: Tangential — sources relate but don't really answer this specific ticket.
   - 1: No real support in sources; should have refused.

Return ONLY a JSON object with these fields:
{
  "answer": "<text or empty>",
  "cited_sources": ["kb_xxx", ...],
  "confidence": 1-5,
  "confidence_reason": "<one sentence>",
  "ambiguity_notes": "<optional, note any missing details you had to assume>",
  "refused": false
}"""


def _format_sources(hits: list[KBHit]) -> str:
    lines = []
    for h in hits:
        lines.append(f"--- SOURCE {h.doc_id} | title: {h.title} | similarity: {h.score:.2f}\n{h.snippet}")
    return "\n".join(lines)


class Generator:
    def __init__(self) -> None:
        self._llm = get_llm()

    def generate(self, ticket: str, hits: list[KBHit]) -> GenerationResult:
        user = f"TICKET:\n{ticket}\n\nSOURCES:\n{_format_sources(hits)}"
        try:
            data = self._llm.complete_json(_SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            return GenerationResult(
                answer="",
                cited_sources=[],
                confidence=1,
                confidence_reason=f"generator error: {e!s}",
                refused=True,
            )

        # Normalise fields — models sometimes return confidence as a string.
        try:
            conf = int(data.get("confidence", 1))
        except (TypeError, ValueError):
            conf = 1
        conf = max(1, min(5, conf))

        cited = data.get("cited_sources") or []
        if isinstance(cited, str):
            cited = [cited]
        cited = [c for c in cited if isinstance(c, str) and c.startswith("kb_")]

        return GenerationResult(
            answer=str(data.get("answer") or "").strip(),
            cited_sources=cited,
            confidence=conf,
            confidence_reason=str(data.get("confidence_reason") or "")[:400],
            ambiguity_notes=str(data.get("ambiguity_notes") or "")[:400],
            refused=bool(data.get("refused", False)) or not str(data.get("answer") or "").strip(),
        )
