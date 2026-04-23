"""Orchestrator. Composes the six boundary layers into a single Decision.

  Layer 1  High-risk intent  ──► ESCALATE (rg | legal | fraud | selfharm)
  Layer 2  OOD classifier    ──► ESCALATE (out_of_scope)
  Layer 3  Retrieval gate    ──► ESCALATE (low_retrieval) if top < SIM_THRESHOLD
  Layer 4  Generator         ──► ESCALATE (low_confidence) if refused
  Layer 5  Verifier          ──► ESCALATE (hallucination) if not grounded
  Layer 6  Confidence gate   ──► ESCALATE (low_confidence) if conf < THRESHOLD
                              ──► ANSWER otherwise

The order is deliberate (see README > Design decisions). In particular,
high-risk is checked BEFORE OOD — a "nothing matters" message should not
be dismissed as off-topic.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from . import retriever
from .classifiers import HighRiskClassifier, OODClassifier
from .config import settings
from .generator import Generator
from .schemas import Decision, TraceStep
from .verifier import Verifier

log = logging.getLogger(__name__)


# --- safe operator messages per escalation reason -------------------------

_OPERATOR_MESSAGES = {
    "out_of_scope": (
        "The question is not related to AurumPlay account/payment/game support. "
        "A human agent should either redirect the user or politely decline."
    ),
    "high_risk_rg": (
        "Responsible-gambling signal detected. Do NOT send an automated reply. "
        "Route to a trained RG-aware agent. Offer GamCare / BeGambleAware / "
        "Gambling Therapy resources and, if appropriate, a self-exclusion or "
        "cooling-off flow."
    ),
    "high_risk_legal": (
        "Legal / regulator threat detected. Do NOT improvise. Route to the "
        "compliance / legal escalation queue."
    ),
    "high_risk_fraud": (
        "Account-takeover / unauthorised activity claim detected. Freeze the "
        "account for investigation and route to the fraud / security queue."
    ),
    "high_risk_selfharm": (
        "Self-harm language detected. This is a safety-first case. Do NOT "
        "send a templated reply. Route immediately to a human agent trained "
        "for mental-health-adjacent conversations and surface crisis-line "
        "resources."
    ),
    "low_retrieval": (
        "The knowledge base does not cover this question well enough to "
        "answer automatically. A human agent should respond and, if the "
        "topic is recurring, the question should be added to the KB."
    ),
    "hallucination": (
        "The draft answer contained claims not grounded in the knowledge "
        "base. A human agent should compose the reply from scratch."
    ),
    "low_confidence": (
        "The model could not answer with sufficient confidence. A human "
        "agent should review the retrieved sources and respond."
    ),
}


@lru_cache(maxsize=1)
def _pipeline():
    return Pipeline()


def resolve(ticket: str) -> Decision:
    """Convenience module-level entry point used by the API and eval.py."""
    return _pipeline().resolve(ticket)


class Pipeline:
    def __init__(self) -> None:
        self.high_risk = HighRiskClassifier()
        self.ood = OODClassifier()
        self.generator = Generator()
        self.verifier = Verifier()

    # --------------------------------------------------------------------

    def resolve(self, ticket: str) -> Decision:
        t0 = time.perf_counter()
        trace: list[TraceStep] = []

        # Layer 1 — high-risk ------------------------------------------------
        hr = self.high_risk.classify(ticket)
        trace.append(TraceStep(step="high_risk", result=hr.model_dump()))
        if hr.is_high_risk:
            reason = f"high_risk_{hr.category}"  # matches EscalationReason literals
            return self._escalate(reason, trace, t0)  # type: ignore[arg-type]

        # Layer 2 — out-of-domain --------------------------------------------
        ood = self.ood.classify(ticket)
        trace.append(TraceStep(step="ood", result=ood.model_dump()))
        if not ood.in_domain:
            return self._escalate("out_of_scope", trace, t0)

        # Layer 3 — retrieval + similarity gate ------------------------------
        hits = retriever.search(ticket, k=settings.top_k)
        top_score = hits[0].score if hits else 0.0
        trace.append(TraceStep(
            step="retrieval",
            result={
                "top_similarity": round(top_score, 3),
                "k": len(hits),
                "doc_ids": [h.doc_id for h in hits],
                "scores": [round(h.score, 3) for h in hits],
            },
        ))
        if not hits or top_score < settings.sim_threshold:
            return self._escalate("low_retrieval", trace, t0)

        # Layer 4 — generation -----------------------------------------------
        gen = self.generator.generate(ticket, hits)
        trace.append(TraceStep(
            step="generation",
            result={
                "confidence": gen.confidence,
                "confidence_reason": gen.confidence_reason,
                "cited_sources": gen.cited_sources,
                "refused": gen.refused,
            },
        ))
        if gen.refused:
            return self._escalate("low_confidence", trace, t0, pre_answer=gen)

        # Layer 5 — verifier -------------------------------------------------
        ver = self.verifier.verify(ticket, gen.answer, hits)
        trace.append(TraceStep(step="verifier", result=ver.model_dump()))
        if ver.grounded != "grounded":
            return self._escalate("hallucination", trace, t0, pre_answer=gen)

        # Layer 6 — confidence gate ------------------------------------------
        if gen.confidence < settings.confidence_threshold:
            return self._escalate("low_confidence", trace, t0, pre_answer=gen)

        # --- Answer ---------------------------------------------------------
        trace.append(TraceStep(step="total_ms", result={"ms": int((time.perf_counter() - t0) * 1000)}))
        return Decision(
            decision="answer",
            answer=gen.answer,
            sources=gen.cited_sources,
            confidence=gen.confidence,
            reasoning_trace=trace,
            message_to_operator="",
        )

    # --------------------------------------------------------------------

    def _escalate(self, reason, trace, t0, pre_answer=None) -> Decision:
        trace.append(TraceStep(step="total_ms", result={"ms": int((time.perf_counter() - t0) * 1000)}))
        return Decision(
            decision="escalate",
            escalation_reason=reason,
            answer=None,
            sources=pre_answer.cited_sources if pre_answer else [],
            confidence=pre_answer.confidence if pre_answer else None,
            reasoning_trace=trace,
            message_to_operator=_OPERATOR_MESSAGES.get(reason, "Manual review needed."),
        )
