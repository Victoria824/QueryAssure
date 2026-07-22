from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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


app = FastAPI(title="DataAgentKit SQL Agent", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _paths() -> tuple[Path, Path]:
    database = Path(os.getenv("DATAAGENTKIT_DATABASE", "data/retail.duckdb"))
    catalog = Path(os.getenv("DATAAGENTKIT_CATALOG", "metadata/catalog.yml"))
    return database, catalog


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo-ready"}


@app.get("/api/schema")
def schema() -> dict:
    _, catalog_path = _paths()
    catalog = Catalog.from_yaml(catalog_path)
    return {"tables": catalog.tables, "metrics": catalog.metrics}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    database, catalog_path = _paths()
    catalog = Catalog.from_yaml(catalog_path)
    provider = OpenAIProvider() if request.live else None
    trace = SqlAgent(database, catalog, provider).ask(request.question)
    return trace.to_dict()


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
