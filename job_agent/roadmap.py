"""Join table: market skill demand -> your sprint-roadmap coverage.

Curated from the AI-Engineer roadmap + Munich market analysis. This is legitimate
domain knowledge, not something to RAG over 17 notes for — keep it as code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Status = Literal["covered", "partial", "gap"]


class Coverage(BaseModel):
    status: Status
    where: str


ROADMAP_COVERAGE: dict[str, Coverage] = {
    "python": Coverage(status="covered", where="Drills W1–16 (you already know it)"),
    "typescript": Coverage(status="covered", where="Sprint 1 — Atlas UI"),
    "llm-apis": Coverage(status="covered", where="Sprint 1 W1"),
    "rag": Coverage(status="covered", where="Sprint 2 (Sage) — whole sprint"),
    "prompt-engineering": Coverage(status="covered", where="Sprint 1 W2"),
    "langchain-langgraph": Coverage(status="covered", where="Sprint 2 W7"),
    "agents": Coverage(status="covered", where="Sprint 1–2"),
    "tool-use": Coverage(status="covered", where="Sprint 1 W2"),
    "pytorch": Coverage(status="covered", where="Sprint 3 (Aug) — late"),
    "deep-learning": Coverage(status="covered", where="Sprint 3"),
    "nlp": Coverage(status="covered", where="Sprint 1/3 (transformers)"),
    "fine-tuning": Coverage(status="covered", where="Sprint 4 (Sep) — late"),
    "huggingface": Coverage(status="covered", where="Sprint 4"),
    "vector-databases": Coverage(status="covered", where="Sprint 2 (Qdrant/pgvector)"),
    "evals": Coverage(status="covered", where="Sprint 1 W3 ⭐ + RAGAS S2 (your differentiator)"),
    "docker": Coverage(status="partial", where="Qdrant S2, FastAPI S4 — light"),
    "cloud-azure": Coverage(status="gap", where="NOT in plan — Munich enterprise is Azure-heavy; add a deploy"),
    "cloud-aws": Coverage(status="gap", where="NOT in plan"),
    "cloud-gcp": Coverage(status="gap", where="NOT in plan"),
    "sql": Coverage(status="partial", where="pgvector touches Postgres only"),
    "pandas-numpy-sklearn": Coverage(status="partial", where="NumPy S3 prep; pandas/sklearn light"),
    "git": Coverage(status="covered", where="daily"),
    "computer-vision": Coverage(status="gap", where="deliberately cut"),
    "multimodal": Coverage(status="gap", where="deliberately cut (asked by some Munich roles)"),
    "mlops": Coverage(status="gap", where="explicitly cut to backlog"),
    "other": Coverage(status="gap", where="unmapped — inspect the raw phrase"),
}


class DemandRow(BaseModel):
    skill: str
    mentions: int
    required: int


class RankedRow(DemandRow):
    status: Status
    where: str


def match_roadmap(rows: list[DemandRow]) -> list[RankedRow]:
    ranked = [
        RankedRow(**r.model_dump(), **ROADMAP_COVERAGE[r.skill].model_dump())
        for r in rows
    ]
    ranked.sort(key=lambda r: r.mentions, reverse=True)
    return ranked


def list_concepts() -> list[str]:
    """Live read of your vault's concept spine — a freshness signal (graceful if absent)."""
    root = Path(os.environ.get("CONCEPTS_DIR", "C:/Users/AliAlpOezer/dev/ai-sprint-vault/Concepts"))
    try:
        return sorted(p.stem for p in root.glob("*.md"))
    except OSError:
        return []
