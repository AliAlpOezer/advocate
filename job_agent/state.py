"""Graph state. Lists written by parallel (Send) branches use an `add` reducer so
concurrent updates merge instead of clobbering each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

from .roadmap import DemandRow, RankedRow
from .skills import ExtractedSkill
from .sources import Job


class SearchQuery(BaseModel):
    keywords: str
    location: str
    geo_id: str


class PostingSkills(BaseModel):
    job_id: str
    title: str
    company: str
    url: str | None
    skills: list[ExtractedSkill]


class JobAgentState(TypedDict, total=False):
    goal: str
    query: SearchQuery
    sources: list[str]
    # Written by parallel source agents -> merge.
    raw_jobs: Annotated[list[Job], operator.add]
    jobs: list[Job]
    # Written by parallel extract branches -> merge.
    skills: Annotated[list[PostingSkills], operator.add]
    demand: list[DemandRow]
    ranked: list[RankedRow]
    report: str
