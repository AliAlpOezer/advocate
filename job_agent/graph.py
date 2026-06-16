"""The LangGraph supervisor graph.

    START -> planner
          -> (Send fan-out) per source agent  [context isolation]
          -> collect (dedup)
          -> (Send fan-out) per posting -> extract  [map]
          -> roadmap (tally + join)  [reduce, deterministic]
          -> synthesize (LLM report) -> END

LLM is used only where it earns it: extraction and synthesis. Fetch/parse/tally
stay deterministic. Compile with a checkpointer (see cli.py) for resumable runs.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .extract import extract_skills
from .llm import build_system_prefix
from .roadmap import DemandRow, RankedRow, match_roadmap
from .sources import (
    dedupe,
    fetch_arbeitnow,
    fetch_description,
    is_aiish,
    search_linkedin_guest,
)
from .state import JobAgentState, PostingSkills, SearchQuery

SOURCES = ["arbeitnow", "linkedin"]


def _build_demand(postings: list[PostingSkills]) -> list[DemandRow]:
    mentions: dict[str, int] = {}
    required: dict[str, int] = {}
    for p in postings:
        seen: set[str] = set()
        for s in p.skills:
            if s.canonical in seen:  # count each skill once per posting
                continue
            seen.add(s.canonical)
            mentions[s.canonical] = mentions.get(s.canonical, 0) + 1
            if s.required:
                required[s.canonical] = required.get(s.canonical, 0) + 1
    return [DemandRow(skill=k, mentions=v, required=required.get(k, 0)) for k, v in mentions.items()]


def format_table(ranked: list[RankedRow]) -> str:
    icon = {"covered": "✅", "partial": "⚠️", "gap": "❌"}
    lines = [
        "   # | skill                  | jobs | req | your plan",
        "  ---|------------------------|------|-----|----------",
    ]
    for i, r in enumerate(ranked, 1):
        lines.append(
            f"  {i:>2} | {r.skill:<22} | {r.mentions:>4} | {r.required:>3} | "
            f"{icon[r.status]} {r.where}"
        )
    return "\n".join(lines)


def build_graph(llm: BaseChatModel, provider: str, top_n: int):
    def planner(state: JobAgentState) -> dict:
        # Deterministic: finalize the query + source set. (LLM keyword expansion is a
        # natural extension point, but honest engineering keeps this node code.)
        return {"sources": SOURCES}

    def route_to_sources(state: JobAgentState) -> list[Send]:
        q = state["query"]
        return [Send(f"source_{s}", {"query": q}) for s in state["sources"]]

    def source_arbeitnow(state: JobAgentState) -> dict:
        return {"raw_jobs": [j for j in fetch_arbeitnow() if is_aiish(j)]}

    def source_linkedin(state: JobAgentState) -> dict:
        q = state["query"]
        return {"raw_jobs": search_linkedin_guest(q.keywords, q.location, q.geo_id)}

    def collect(state: JobAgentState) -> dict:
        jobs = [j for j in dedupe(state.get("raw_jobs", [])) if j.job_id][:top_n]
        return {"jobs": jobs}

    def route_to_extract(state: JobAgentState) -> list[Send]:
        if not state["jobs"]:
            return [Send("roadmap", {})]  # nothing to extract; skip to reduce
        return [Send("extract", {"job": j}) for j in state["jobs"]]

    def extract(state: JobAgentState) -> dict:
        job = state["job"]  # type: ignore[typeddict-item]  (Send payload)
        jd = fetch_description(job.job_id)
        skills = extract_skills(llm, provider, job.title, jd)
        print(f"  ✓ {job.title} — {job.company}")
        return {
            "skills": [
                PostingSkills(
                    job_id=job.job_id, title=job.title, company=job.company,
                    url=job.url, skills=skills,
                )
            ]
        }

    def roadmap(state: JobAgentState) -> dict:
        ranked = match_roadmap(_build_demand(state.get("skills", [])))
        return {"ranked": ranked}

    def synthesize(state: JobAgentState) -> dict:
        ranked = state["ranked"]
        gaps = [r.skill for r in ranked if r.status == "gap" and r.skill != "other" and r.mentions > 0]
        table = format_table(ranked)
        try:
            prefix = build_system_prefix(
                provider,
                "You are a careful career analyst. Given a ranked table of skill demand "
                "across Munich AI job postings and the candidate's roadmap coverage, write a "
                "concise markdown brief: the top demanded skills, which are covered vs gaps, "
                "and one prioritized recommendation. Be specific, no fluff.",
            )
            msg = HumanMessage(
                content=f"RANKED DEMAND TABLE:\n{table}\n\nHIGH-DEMAND GAPS: {', '.join(gaps) or 'none'}"
            )
            report = str(llm.invoke([prefix, msg]).content).strip()
        except Exception as err:  # noqa: BLE001 — fall back to the deterministic table
            print(f"  ⚠️  synthesis LLM failed ({err}); using deterministic table.")
            report = f"📊 Skill demand:\n\n{table}\n\n⚠️  High-demand GAPS: {', '.join(gaps) or 'none'}"
        return {"report": report}

    g = StateGraph(JobAgentState)
    g.add_node("planner", planner)
    g.add_node("source_arbeitnow", source_arbeitnow)
    g.add_node("source_linkedin", source_linkedin)
    g.add_node("collect", collect)
    g.add_node("extract", extract)
    g.add_node("roadmap", roadmap)
    g.add_node("synthesize", synthesize)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", route_to_sources, ["source_arbeitnow", "source_linkedin"])
    g.add_edge("source_arbeitnow", "collect")
    g.add_edge("source_linkedin", "collect")
    g.add_conditional_edges("collect", route_to_extract, ["extract", "roadmap"])
    g.add_edge("extract", "roadmap")
    g.add_edge("roadmap", "synthesize")
    g.add_edge("synthesize", END)
    return g
