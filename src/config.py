"""Runtime configuration.

All thresholds live here so they can be tuned from .env without editing code.
Values here are the defaults the eval harness was calibrated against.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # --- paths ---
    # `removeprefix("./")` peels "./foo" → "foo" but keeps ".chroma" as
    # ".chroma" (lstrip would also eat the leading dot).
    kb_dir: Path = ROOT / os.getenv("KB_DIR", "knowledge_base").removeprefix("./")
    chroma_dir: Path = ROOT / os.getenv("CHROMA_DIR", ".chroma").removeprefix("./")

    # --- retrieval ---
    # Multilingual MiniLM — 384 dim, supports 50+ languages. Chosen over the
    # English-only all-MiniLM-L6-v2 because our target markets (Parimatch
    # Asia / Africa / LatAm) generate tickets in multiple languages against
    # an English KB; monolingual embeddings would tank retrieval on those.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    chunk_size_words: int = 180
    chunk_overlap_words: int = 30
    top_k: int = 5

    # --- boundary thresholds ---
    # cosine similarity below this -> low_retrieval escalation
    sim_threshold: float = float(os.getenv("SIM_THRESHOLD", "0.45"))
    # self-rated confidence (1-5) below this -> low_confidence escalation
    confidence_threshold: int = int(os.getenv("CONFIDENCE_THRESHOLD", "4"))

    # --- llm ---
    groq_api_key: str | None = os.getenv("GROQ_API_KEY") or None
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    # --- misc ---
    collection_name: str = "aurumplay_kb"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()


def backend() -> str:
    """Return the LLM backend to use, based on which key is present."""
    if settings.groq_api_key:
        return "groq"
    if settings.anthropic_api_key:
        return "anthropic"
    return "mock"
