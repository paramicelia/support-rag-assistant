"""Smoke tests for the full pipeline against a small sample.

Runs the mock backend so no API key is needed. Verifies that each boundary
layer escalates on its intended trigger — NOT that answers are correct
(that's what eval.py is for).
"""

from __future__ import annotations

import pytest

from src import pipeline


@pytest.fixture(scope="module", autouse=True)
def _ensure_kb_ingested():
    """If the collection is empty, ingest it. Skips the test module if
    chromadb is unavailable at import time."""
    from src.ingest import get_collection, ingest
    col = get_collection(reset=False)
    if col.count() == 0:
        ingest(reset=True)


def test_high_risk_rg_escalates() -> None:
    d = pipeline.resolve("I cant stop playing, lost everything this month")
    assert d.decision == "escalate"
    assert d.escalation_reason == "high_risk_rg"
    # High-risk should short-circuit BEFORE retrieval runs
    steps = [s.step for s in d.reasoning_trace]
    assert "retrieval" not in steps
    assert "GamCare" in d.message_to_operator


def test_fraud_escalates() -> None:
    d = pipeline.resolve("Someone hacked my account and withdrew 5000 dollars")
    assert d.decision == "escalate"
    assert d.escalation_reason == "high_risk_fraud"


def test_out_of_scope_escalates() -> None:
    d = pipeline.resolve("What's the weather in Warsaw?")
    assert d.decision == "escalate"
    assert d.escalation_reason == "out_of_scope"


def test_in_kb_question_answers() -> None:
    d = pipeline.resolve("How do I withdraw to my Visa card?")
    assert d.decision == "answer"
    assert d.sources  # non-empty
    assert d.confidence is not None and d.confidence >= 4


def test_reasoning_trace_is_populated() -> None:
    d = pipeline.resolve("How do I reset my password?")
    steps = [s.step for s in d.reasoning_trace]
    # At minimum we always log high_risk and total_ms
    assert "high_risk" in steps
    assert "total_ms" in steps
