"""FastAPI wrapper around the pipeline.

Endpoints:
  GET  /health        — liveness
  POST /resolve       — decide on a ticket, returns a full Decision
  GET  /kb/stats      — quick sanity check of the indexed KB

Run locally: `uvicorn src.api:app --reload`. Swagger UI at /docs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pipeline
from .config import backend, settings
from .ingest import get_collection
from .schemas import Decision

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="AurumPlay Support RAG",
    description="RAG-backed support assistant with explicit boundary layers.",
    version="0.1.0",
)


class ResolveRequest(BaseModel):
    ticket: str = Field(min_length=1, max_length=4000, description="Customer message to resolve.")


class HealthResponse(BaseModel):
    status: str
    backend: str
    sim_threshold: float
    confidence_threshold: int


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        backend=backend(),
        sim_threshold=settings.sim_threshold,
        confidence_threshold=settings.confidence_threshold,
    )


@app.post("/resolve", response_model=Decision)
def resolve(req: ResolveRequest) -> Decision:
    try:
        return pipeline.resolve(req.ticket)
    except Exception as e:  # noqa: BLE001 — return a clean 500 to the API client
        raise HTTPException(status_code=500, detail=f"pipeline error: {e!s}") from e


@app.get("/kb/stats")
def kb_stats() -> dict[str, Any]:
    col = get_collection(reset=False)
    count = col.count()
    return {
        "collection": settings.collection_name,
        "chunk_count": count,
        "embedding_model": settings.embedding_model,
    }


# --- UI -------------------------------------------------------------------
# Mount the single-page pipeline viewer at the root. `GET /` serves
# ui/index.html; other static assets (if any are ever added) are served
# from /ui/. Keeping it one file with inline CSS/JS means no build step,
# no npm, no framework — open the URL and it works.

if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")
