"""Unit tests for the high-risk classifier.

This is the critical boundary: a false negative here is the worst failure
mode the whole system has. Tests cover each category in each language we
claim support for. The classifier is keyword-based so these tests are
deterministic and cheap to run in CI.
"""

from __future__ import annotations

import pytest

from src.classifiers import HighRiskClassifier


@pytest.fixture(scope="module")
def clf() -> HighRiskClassifier:
    return HighRiskClassifier()


# --- Responsible gambling -------------------------------------------------

@pytest.mark.parametrize("text", [
    "I can't stop playing, please help me stop",
    "I'm addicted and I've lost everything this month",
    "cannot stop gambling, it ruined my family",
    "не могу остановиться, проиграл всё",
    "не можу зупинитися, програв все",
    "tenho vício em jogo, perdi tudo",
])
def test_rg_detected(clf: HighRiskClassifier, text: str) -> None:
    r = clf.classify(text)
    assert r.is_high_risk, f"RG signal missed: {text!r}"
    assert r.category == "rg"


# --- Legal --------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "My lawyer will contact you tomorrow",
    "I will sue you in court",
    "I will report you to the MGA regulator",
    "Я буду жаловаться в регулятор",
    "жалуюсь в регулятор",
    "скаргу до регулятора",
])
def test_legal_detected(clf: HighRiskClassifier, text: str) -> None:
    r = clf.classify(text)
    assert r.is_high_risk, f"Legal signal missed: {text!r}"
    assert r.category == "legal"


# --- Fraud -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Someone hacked into my account and withdrew 5000",
    "My account was hacked last night",
    "An unauthorized withdrawal was made, it wasn't me",
    "мой аккаунт взломали, украли деньги",
    "зламали акаунт, вкрали кошти",
])
def test_fraud_detected(clf: HighRiskClassifier, text: str) -> None:
    r = clf.classify(text)
    assert r.is_high_risk
    assert r.category == "fraud"


# --- Self-harm ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I want to kill myself after losing everything",
    "I will end it all tonight",
    "Nothing matters anymore, I don't see the point",
    "не вижу смысла жить после этих потерь",
])
def test_selfharm_detected(clf: HighRiskClassifier, text: str) -> None:
    r = clf.classify(text)
    assert r.is_high_risk
    assert r.category == "selfharm"


# --- Self-harm beats RG when both present -----------------------------

def test_selfharm_beats_rg(clf: HighRiskClassifier) -> None:
    """If the ticket has both RG and self-harm signals, self-harm wins —
    it's the category that needs the most care in handoff."""
    r = clf.classify("I can't stop playing and I want to kill myself")
    assert r.category == "selfharm"


# --- Negatives -- must NOT fire on benign tickets ---------------------

@pytest.mark.parametrize("text", [
    "How do I withdraw to my Visa card?",
    "Forgot my password, how to reset?",
    "What is wagering and how much do I need to bet?",
    "Deposited via USDT TRC20 but my balance didn't change",
    "What's the weather in Warsaw?",
    "Write me a poem about poker",
])
def test_benign_passes_through(clf: HighRiskClassifier, text: str) -> None:
    r = clf.classify(text)
    assert not r.is_high_risk, f"False positive on: {text!r} (got {r.category})"
