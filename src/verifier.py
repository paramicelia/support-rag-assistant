"""Hallucination verifier — second LLM pass.

We send the generated answer back to the model together with the retrieved
sources and ask: does every factual claim in the answer come from the
sources? Three-way grounded / partial / not_grounded.

This is a classic LLM-as-judge setup. It won't catch every hallucination,
but it reliably catches:
- Answers that cite a source that wasn't provided
- Answers that add plausible-sounding timelines or amounts
- Answers that drift into recommendations beyond the KB
"""

from __future__ import annotations

from .llm import get_llm
from .schemas import KBHit, VerifierResult

_SYSTEM = """You are a grounding verifier for a support assistant.

You receive:
- TICKET: the original customer question
- ANSWER: the assistant's draft answer
- SOURCES: the knowledge-base snippets used to write it

Decide how well the ANSWER is grounded in the SOURCES:
- "grounded": every factual claim in the answer is directly supported by the sources. Restating, paraphrasing, reformatting are fine.
- "partial": most of the answer is supported, but 1-2 specific facts (a number, a timeline, a policy detail) are not in the sources.
- "not_grounded": the answer contains substantial claims that are not in the sources, or it cites a source id not in the provided sources.

Return ONLY a JSON object: {"grounded": "grounded"|"partial"|"not_grounded", "rationale": "<one sentence>"}"""


def _format_sources(hits: list[KBHit]) -> str:
    return "\n".join(f"[{h.doc_id}] {h.snippet}" for h in hits)


class Verifier:
    def __init__(self) -> None:
        self._llm = get_llm()

    def verify(self, ticket: str, answer: str, hits: list[KBHit]) -> VerifierResult:
        if not answer.strip():
            return VerifierResult(grounded="not_grounded", rationale="empty answer")

        user = (
            f"TICKET:\n{ticket}\n\n"
            f"ANSWER:\n{answer}\n\n"
            f"SOURCES:\n{_format_sources(hits)}"
        )
        try:
            data = self._llm.complete_json(_SYSTEM, user)
        except Exception as e:  # noqa: BLE001
            # Fail CLOSED: if the verifier itself fails, treat as ungrounded.
            # An extra escalation is cheap; a missed hallucination is not.
            return VerifierResult(grounded="not_grounded", rationale=f"verifier error: {e!s}")

        grounded = str(data.get("grounded", "not_grounded")).lower()
        if grounded not in ("grounded", "partial", "not_grounded"):
            grounded = "not_grounded"
        return VerifierResult(grounded=grounded, rationale=str(data.get("rationale", ""))[:400])  # type: ignore[arg-type]
