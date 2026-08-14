"""CLI entrypoint:  python -m job_agent.cli "ai engineer werkstudent" "Munich" 100477049

Compiles the graph with a SQLite checkpointer (durable + resumable). Re-running with
the same --thread resumes from the last checkpoint instead of re-fetching.
"""

from __future__ import annotations

import argparse
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

# Windows consoles default to cp1252 and choke on the report's emoji/✅. Force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .config import assert_key, resolve
from .graph import build_graph
from .llm import get_llm
from .roadmap import list_concepts
from .state import SearchQuery


def main() -> None:
    ap = argparse.ArgumentParser(description="Munich AI job-market agent (LangGraph)")
    ap.add_argument("keywords", nargs="?", default="ai engineer werkstudent")
    ap.add_argument("location", nargs="?", default="Munich")
    ap.add_argument("geo_id", nargs="?", default="100477049")
    ap.add_argument("top_n", nargs="?", type=int, default=8)
    ap.add_argument("--provider", choices=["openrouter", "anthropic"])
    ap.add_argument("--model")
    ap.add_argument("--thread", help="resume a prior run by thread id")
    args = ap.parse_args()

    cfg = resolve(
        provider=args.provider, model=args.model,
        keywords=args.keywords, location=args.location,
        geo_id=args.geo_id, top_n=args.top_n,
    )
    assert_key(cfg.provider)

    llm = get_llm(cfg.provider, cfg.model)
    builder = build_graph(llm, cfg.provider, cfg.top_n)
    thread_id = args.thread or f"{cfg.keywords}|{cfg.location}|{cfg.geo_id}"

    query = SearchQuery(keywords=cfg.keywords, location=cfg.location, geo_id=cfg.geo_id)
    print(f'\n🔎 "{cfg.keywords}" near {cfg.location} via {cfg.provider}:{cfg.model} — reading descriptions…\n')

    with SqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        final = graph.invoke(
            {"goal": cfg.keywords, "query": query, "raw_jobs": [], "skills": []},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 50},
        )

    print(f"\n{final['report']}\n")
    print(f"🧠 Vault concept spine: {len(list_concepts())} notes detected.\n")


if __name__ == "__main__":
    main()
