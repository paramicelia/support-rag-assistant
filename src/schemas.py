"""Pydantic models — the wire contract for the pipeline.

The Decision object is what the API returns and what eval.py scores against.
It is intentionally fat: reasoning_trace is a big part of the deliverable
because it makes every boundary decision auditable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EscalationReason = Literal[
    "out_of_scope",
    "high_risk_rg",       # responsible gambling
    "high_risk_legal",    # legal threats / regulator
    "high_risk_fraud",    # account takeover, chargeback fraud
    "high_risk_selfharm",
    "low_retrieval",
    "hallucination",
    "low_confidence",
]


class KBHit(BaseModel):
    doc_id: str
    title: str
    category: str
    snippet: str
    score: float  # cosine similarity in [0, 1]


class OODResult(BaseModel):
    in_domain: bool
    reason: str


class HighRiskResult(BaseModel):
    is_high_risk: bool
    category: Literal["rg", "legal", "fraud", "selfharm", "none"] = "none"
    evidence: str = ""


class GenerationResult(BaseModel):
    answer: str
    cited_sources: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=1, le=5)
    confidence_reason: str = ""
    ambiguity_notes: str = ""
    refused: bool = False  # true if the LLM decided it cannot answer from sources


class VerifierResult(BaseModel):
    grounded: Literal["grounded", "partial", "not_grounded"]
    rationale: str = ""


class TraceStep(BaseModel):
    step: str
    result: dict


class Decision(BaseModel):
    decision: Literal["answer", "escalate"]
    escalation_reason: EscalationReason | None = None
    answer: str | None = None
    sources: list[str] = Field(default_factory=list)
    confidence: int | None = None
    reasoning_trace: list[TraceStep] = Field(default_factory=list)

    # Human-facing message the support agent (or user) sees. For escalations
    # this explains *why* we kept quiet instead of inventing an answer.
    message_to_operator: str = ""
