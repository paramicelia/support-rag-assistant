"""Ingest the knowledge_base/ markdown files into ChromaDB.

Run with: `python -m src.ingest`

Chunking: word-based (180 words, 30-word overlap). For a KB of this size
(20 articles, ~5k total words) a simpler chunker beats a token-aware one:
fewer moving parts, easier to reason about. A bigger KB would want a
tokeniser-aware splitter.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from .config import settings

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


# --- frontmatter parsing --------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class Article:
    doc_id: str
    title: str
    category: str
    keywords: list[str]
    body: str

    @classmethod
    def from_file(cls, path: Path) -> "Article":
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise ValueError(f"{path.name}: missing frontmatter")
        frontmatter, body = m.group(1), m.group(2)

        meta: dict[str, str] = {}
        for line in frontmatter.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

        keywords_raw = meta.get("keywords", "[]").strip()
        keywords = [k.strip().strip("'\"") for k in keywords_raw.strip("[]").split(",") if k.strip()]

        return cls(
            doc_id=meta.get("id", path.stem),
            title=meta.get("title", path.stem).strip('"'),
            category=meta.get("category", "uncategorized"),
            keywords=keywords,
            body=body.strip(),
        )


# --- chunking -------------------------------------------------------------

def chunk_words(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]

    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunk = words[start : start + size]
        if not chunk:
            break
        chunks.append(" ".join(chunk))
        if start + size >= len(words):
            break
    return chunks


# --- ingestion ------------------------------------------------------------

def load_articles() -> list[Article]:
    files = sorted(settings.kb_dir.glob("kb_*.md"))
    if not files:
        raise FileNotFoundError(f"No kb_*.md files in {settings.kb_dir}")
    return [Article.from_file(p) for p in files]


def get_collection(reset: bool = False):
    client = chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
    )
    if reset:
        try:
            client.delete_collection(settings.collection_name)
        except Exception:  # noqa: BLE001 — chroma raises a plain Exception if not found
            pass
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def ingest(reset: bool = True) -> None:
    articles = load_articles()
    log.info("Loaded %d articles from %s", len(articles), settings.kb_dir)

    encoder = SentenceTransformer(settings.embedding_model)
    collection = get_collection(reset=reset)

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []

    for art in articles:
        chunks = chunk_words(art.body, settings.chunk_size_words, settings.chunk_overlap_words)
        for i, chunk in enumerate(chunks):
            # Prepend the title to every chunk — it's a free signal that
            # lifts retrieval on short queries.
            text = f"[{art.title}] {chunk}"
            ids.append(f"{art.doc_id}::chunk_{i:02d}")
            docs.append(text)
            metas.append({
                "doc_id": art.doc_id,
                "title": art.title,
                "category": art.category,
                "keywords": ", ".join(art.keywords),
                "chunk_idx": i,
            })

    log.info("Encoding %d chunks with %s", len(docs), settings.embedding_model)
    embeddings = encoder.encode(docs, show_progress_bar=False, normalize_embeddings=True).tolist()

    collection.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
    log.info("Stored %d chunks in collection '%s'", len(docs), settings.collection_name)


if __name__ == "__main__":
    ingest(reset=True)
