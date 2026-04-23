"""LLM client abstraction.

Three backends:

- Groq (primary) — fast + generous free tier, JSON mode via response_format
- Anthropic (backup) — Claude Haiku with prompt caching on the system prompt
- Mock — deterministic rule-based responder so the eval harness and unit
  tests run without API keys. Mock is NOT meant for the demo — it is a
  fallback so nothing in this repo requires a paid account just to check
  that the plumbing works.

All backends implement the same `.complete_json(system, user) -> dict` and
`.complete_text(system, user) -> str` interface.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from .config import backend, settings

log = logging.getLogger(__name__)


# --- interface ------------------------------------------------------------

class LLMClient(ABC):
    name: str

    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def complete_text(self, system: str, user: str) -> str:
        ...


# --- Groq -----------------------------------------------------------------

class GroqClient(LLMClient):
    name = "groq"

    def __init__(self) -> None:
        from groq import Groq  # local import so Anthropic-only users don't need the dep at import time
        self._client = Groq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)

    def complete_text(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        return (resp.choices[0].message.content or "").strip()


# --- Anthropic ------------------------------------------------------------

class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self) -> None:
        from anthropic import Anthropic
        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def _complete(self, system: str, user: str) -> str:
        # Cache the system prompt — every layer calls it with the same system.
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0.1,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate any text blocks in the response
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        # Nudge the model to return JSON via prompt; Anthropic has no JSON mode flag.
        system_json = system + "\n\nReturn ONLY a single JSON object. No prose before or after."
        raw = self._complete(system_json, user)
        # Be tolerant of fenced code blocks
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0) if m else raw)

    def complete_text(self, system: str, user: str) -> str:
        return self._complete(system, user)


# --- Mock -----------------------------------------------------------------

class MockClient(LLMClient):
    """Deterministic fake LLM. Pattern-matches the known system prompts.

    This is explicitly labelled as a fallback — the eval still works but
    answer quality is lower than a real LLM. The point is that the pipeline
    is runnable end-to-end on a fresh clone with no keys, so whoever reviews
    this repo can at minimum execute `eval.py` and see the decision logic.
    """

    name = "mock"

    # Keyword cues used by the mock to emulate classifier outputs.
    # Prefix-matching (no closing \b) so stems like "deposit" catch
    # "Deposited" / "deposits" and "verif" catches "verification".
    _OOD_DOMAIN_CUES = re.compile(
        r"\b(kyc|verif|deposit|withdraw|cashout|bonus|wager|rollover|"
        r"spin|slot|casino|betting|bet\b|odds|jackpot|account|password|"
        r"2fa|freespin|mobile app|app for (iphone|android)|affiliate|"
        r"referral|live dealer|"
        r"депозит|вывод|выпла|бонус|аккаунт|казино|ставк|вейджер|верификаци|"
        r"виведенн|поповненн|депозит|забув пароль|забыл пароль)",
        re.I,
    )

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        s = system.lower()
        if "out-of-domain" in s or "ood" in s:
            in_domain = bool(self._OOD_DOMAIN_CUES.search(user))
            return {"in_domain": in_domain,
                    "reason": "matched domain keyword" if in_domain else "no domain keyword detected"}

        if "verifier" in s or "grounded" in s:
            # Very simple heuristic: count kb_xxx references in the answer; if
            # at least one and no obvious invention markers, call it grounded.
            answer = user.lower()
            has_cite = bool(re.search(r"kb_\d{3}", answer))
            suspicious = any(p in answer for p in [" i think ", " i believe ", " probably "])
            if has_cite and not suspicious:
                return {"grounded": "grounded", "rationale": "answer references sources and avoids speculation"}
            return {"grounded": "partial", "rationale": "could not verify every claim from sources"}

        if "structured support answer" in s or "customer support assistant" in s:
            # Prefer parsing the "--- SOURCE kb_xxx" markers (stable, ordered
            # by retrieval score) over a blind regex on the full prompt —
            # otherwise we'd pick up kb_xxx references inside article bodies.
            markers = re.findall(r"--- SOURCE (kb_\d{3})", user)
            kb_id = markers[0] if markers else None
            if not kb_id:
                return {"answer": "", "cited_sources": [], "confidence": 1,
                        "confidence_reason": "no sources provided", "refused": True,
                        "ambiguity_notes": "mock backend; no real answer"}
            return {
                "answer": f"Please see article {kb_id} in our help center for the detailed steps. "
                          "(Mock response — run with GROQ_API_KEY or ANTHROPIC_API_KEY for a real answer.)",
                "cited_sources": [kb_id],
                "confidence": 4,
                "confidence_reason": "mock default",
                "ambiguity_notes": "mock backend",
                "refused": False,
            }

        # Unknown system prompt — fail closed.
        return {}

    def complete_text(self, system: str, user: str) -> str:
        return "(mock response)"


# --- factory --------------------------------------------------------------

_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _singleton
    if _singleton is not None:
        return _singleton

    which = backend()
    if which == "groq":
        _singleton = GroqClient()
    elif which == "anthropic":
        _singleton = AnthropicClient()
    else:
        log.warning("No LLM API key found. Falling back to MOCK LLM — answers will be templated.")
        _singleton = MockClient()
    return _singleton
