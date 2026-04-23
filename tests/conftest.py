"""Test-suite configuration.

Unit tests deliberately pin the LLM backend to the deterministic Mock
regardless of what's in .env. Real-LLM behaviour (Groq/Anthropic) is
slightly non-deterministic even at temperature=0.1 — the verifier can
flip between "grounded" and "partial" on borderline answers, which
makes unit tests flaky without adding any real coverage.

End-to-end LLM quality is the job of `eval.py` (which runs on every
backend explicitly), not pytest.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def force_mock_llm():
    from src import llm, pipeline

    # Swap the LLM singleton first so any freshly-constructed Generator /
    # Verifier / OODClassifier picks up the mock via get_llm().
    llm._singleton = llm.MockClient()

    # Drop the cached Pipeline so a new one is built against the mock.
    pipeline._pipeline.cache_clear()
    pipeline._pipeline()  # warm with mock so the first test call is fast
    yield
