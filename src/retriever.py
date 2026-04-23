"""Semantic retrieval over the ingested KB.

Returns one hit per doc_id (de-duplicated across chunks, keeping the max
score). This matters downstream — the generator sees each article at most
once, which stops the LLM from double-counting evidence.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from .config import settings
from .ingest import get_collection
from .schemas import KBHit


@lru_cache(maxsize=1)
def _encoder() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


@lru_cache(maxsize=1)
def _collection():
    return get_collection(reset=False)


def search(query: str, k: int | None = None) -> list[KBHit]:
    """Return top-k KB hits, de-duplicated by doc_id.

    Note on cosine scoring: Chroma returns a `distance` where a cosine
    distance of 0 means identical. We report similarity = 1 - distance so
    thresholds in config are on the intuitive [-1, 1] scale (in practice
    [0, 1] because embeddings are normalised).
    """
    k = k or settings.top_k
    encoder = _encoder()
    collection = _collection()

    query_emb = encoder.encode([query], normalize_embeddings=True).tolist()
    # Pull more chunks than `k` — after deduplication we may need them.
    n = max(k * 3, 15)
    res = collection.query(query_embeddings=query_emb, n_results=n)

    by_doc: dict[str, KBHit] = {}
    documents = res.get("documents", [[]])[0]
    metadatas = res.get("metadatas", [[]])[0]
    distances = res.get("distances", [[]])[0]

    for doc, meta, dist in zip(documents, metadatas, distances):
        similarity = 1.0 - float(dist)
        doc_id = meta["doc_id"]
        snippet = doc.split("] ", 1)[1] if doc.startswith("[") else doc
        snippet = snippet[:400]
        existing = by_doc.get(doc_id)
        if existing is None or similarity > existing.score:
            by_doc[doc_id] = KBHit(
                doc_id=doc_id,
                title=meta["title"],
                category=meta["category"],
                snippet=snippet,
                score=similarity,
            )

    hits = sorted(by_doc.values(), key=lambda h: h.score, reverse=True)
    return hits[:k]
