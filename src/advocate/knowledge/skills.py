"""Canonical skill vocabulary + extraction schema.

Extraction normalizes every posting's wording to one of these values, so demand
is tally-able and joinable to roadmap coverage (see roadmap.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CANONICAL_SKILLS: tuple[str, ...] = (
    "python", "typescript", "llm-apis", "rag", "prompt-engineering",
    "langchain-langgraph", "agents", "tool-use", "pytorch", "deep-learning",
    "nlp", "fine-tuning", "huggingface", "vector-databases", "evals", "docker",
    "cloud-azure", "cloud-aws", "cloud-gcp", "sql", "pandas-numpy-sklearn",
    "git", "computer-vision", "multimodal", "mlops", "other",
)

CanonicalSkill = Literal[
    "python", "typescript", "llm-apis", "rag", "prompt-engineering",
    "langchain-langgraph", "agents", "tool-use", "pytorch", "deep-learning",
    "nlp", "fine-tuning", "huggingface", "vector-databases", "evals", "docker",
    "cloud-azure", "cloud-aws", "cloud-gcp", "sql", "pandas-numpy-sklearn",
    "git", "computer-vision", "multimodal", "mlops", "other",
]


class ExtractedSkill(BaseModel):
    canonical: CanonicalSkill
    raw: str = Field(description="the exact phrase used in the posting")
    required: bool = Field(description="true if a hard requirement; false if nice-to-have")


class SkillExtraction(BaseModel):
    skills: list[ExtractedSkill] = Field(default_factory=list)
