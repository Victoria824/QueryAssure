from __future__ import annotations

import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .agent import OpenAIProvider, SqlAgent
from .generator import generate_retail_database
from .metadata import Catalog


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    live: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    database, _ = _paths()
    if not database.exists():
        generate_retail_database(database)
    yield


app = FastAPI(title="QueryAssure SQL Agent", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
_CHAT_SLOTS = threading.BoundedSemaphore(
    max(1, int(os.getenv("QUERYASSURE_MAX_CONCURRENT_REQUESTS", "4")))
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _paths() -> tuple[Path, Path]:
    database = Path(os.getenv("QUERYASSURE_DATABASE", "data/retail.duckdb"))
    catalog = Path(os.getenv("QUERYASSURE_CATALOG", "metadata/catalog.yml"))
    return database, catalog


def _require_api_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("QUERYASSURE_API_TOKEN")
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo-ready"}


@app.get("/api/schema", dependencies=[Depends(_require_api_token)])
def schema() -> dict:
    _, catalog_path = _paths()
    catalog = Catalog.from_yaml(catalog_path)
    return {"tables": catalog.tables, "metrics": catalog.metrics}


@app.post("/api/chat", dependencies=[Depends(_require_api_token)])
def chat(request: ChatRequest) -> dict:
    if request.live:
        live_enabled = os.getenv("QUERYASSURE_LIVE_ENABLED", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if not live_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Live model access is disabled",
            )
        if not os.getenv("QUERYASSURE_API_TOKEN"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Live model access requires QUERYASSURE_API_TOKEN",
            )
    if not _CHAT_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The agent is at its concurrency limit",
            headers={"Retry-After": "1"},
        )
    database, catalog_path = _paths()
    try:
        catalog = Catalog.from_yaml(catalog_path)
        provider = OpenAIProvider() if request.live else None
        trace = SqlAgent(database, catalog, provider).ask(request.question)
        return trace.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The agent request failed safely",
        ) from exc
    finally:
        _CHAT_SLOTS.release()


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
