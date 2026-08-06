"""Entry point the draft loop calls instead of shelling out to an agent CLI.

    py -m advocate.apply.cli --repo <advocate-data> --slug <folder> \
        --company ... --title ... --url ... --posting-file ... --report <json>

Two contracts matter to the caller, and both exist because the harness this
replaces honoured neither:

  - **The exit code is honest.** Non-zero whenever no application was produced.
    OpenCode exited 0 on a provider stream error, which is what made its whole
    failover chain unreachable and cost two runs on 2026-08-06.
  - **The report is the real signal.** Even on success it records the turns
    taken, every tool call, and every provider fallback, so "the model made zero
    tool calls" is a value in a file rather than something inferred afterwards
    from an empty folder.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from advocate.apply.graph import MAX_TURNS, build_graph
from advocate.apply.prompt import build_system_prompt, build_task_prompt
from advocate.apply.providers import ChainedChat, default_chain, openrouter_keys
from advocate.apply.tools import build_tools


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="advocate.apply.cli", description=__doc__)
    p.add_argument("--repo", required=True, help="the advocate-data checkout")
    p.add_argument("--slug", required=True, help="applications/<slug>/, the store's primary key")
    p.add_argument("--company", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--posting-file", required=True, help="repo-relative path to posting.md")
    p.add_argument("--report", help="where to write the JSON run report")
    p.add_argument("--skill-dir", help="defaults to <repo>/.claude/skills/cv-drafter")
    p.add_argument("--max-turns", type=int, default=MAX_TURNS)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"no such repository: {repo}", file=sys.stderr)
        return 2
    skill_dir = Path(args.skill_dir) if args.skill_dir else repo / ".claude" / "skills" / "cv-drafter"

    keys = openrouter_keys()
    if not keys:
        print(
            "no OPENROUTER_API_KEY (or _2.._7) in the environment. The drafting chain has "
            "nothing to authenticate with; refusing to start rather than failing per turn.",
            file=sys.stderr,
        )
        return 2

    started = time.time()
    report: dict = {
        "slug": args.slug,
        "ok": False,
        "finished": False,
        "turns": 0,
        "keysAvailable": len(keys),
        "toolCalls": [],
        "attempts": [],
        "summary": "",
        "error": None,
    }

    try:
        system = build_system_prompt(repo, skill_dir)
        task = build_task_prompt(
            slug=args.slug,
            company=args.company,
            title=args.title,
            url=args.url,
            posting_file=args.posting_file,
        )

        sink: list[dict] = []
        tools = build_tools(repo, args.slug, sink)
        llm = ChainedChat(default_chain()).bind_tools(tools)
        app = build_graph(llm, tools, sink, repo)

        print(
            f"[draft-agent] {args.slug}: {len(system):,} chars of grounding material preloaded, "
            f"{len(keys)} key(s), chain: {', '.join(t.model for t in llm.tiers)}",
            file=sys.stderr,
        )

        final = app.invoke(
            {
                "messages": [SystemMessage(content=system), HumanMessage(content=task)],
                "slug": args.slug,
                "turns": 0,
                "finished": False,
                "nudges": 0,
            },
            # The loop already bounds itself with MAX_TURNS; this is the backstop
            # for a pathological tools/agent ping-pong, and each super-step is one
            # node, so it is generous on purpose.
            {"recursion_limit": args.max_turns * 2 + 10},
        )

        report["turns"] = final.get("turns", 0)
        report["finished"] = bool(final.get("finished"))
        report["summary"] = final.get("summary", "")
        report["toolCalls"] = final.get("tool_calls", [])
        report["attempts"] = final.get("attempts", [])
        report["nudges"] = final.get("nudges", 0)
        tail = final["messages"][-1]
        report["lastMessage"] = str(getattr(tail, "content", ""))[:2000]

        writes = [c for c in report["toolCalls"] if c["tool"] == "write_file" and c["ok"]]
        renders = [c for c in report["toolCalls"] if c["tool"] == "render_pdf" and c["ok"]]

        # Success is judged on evidence of work, not on the loop having returned.
        # verify.ts still has the last word on whether the content is any good;
        # this only refuses to claim a draft happened when nothing was written.
        if not report["toolCalls"]:
            report["error"] = (
                "the model made no tool calls at all - it never read the posting or wrote "
                "anything. Treat this as a provider or prompt failure, not a bad draft."
            )
        elif not writes:
            report["error"] = f"no file was written ({len(report['toolCalls'])} tool calls made)"
        elif not renders:
            report["error"] = "no PDF was rendered"
        elif not report["finished"]:
            report["error"] = (
                f"the loop stopped after {report['turns']} turns without calling finish"
            )
        else:
            report["ok"] = True

    except Exception as exc:  # noqa: BLE001 - the report is the contract, not the traceback
        report["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        report["durationSeconds"] = round(time.time() - started, 1)
        if args.report:
            out = Path(args.report)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for line in report["attempts"]:
        print(f"[draft-agent] {line}", file=sys.stderr)
    print(
        f"[draft-agent] {args.slug}: {'ok' if report['ok'] else 'FAILED'} in "
        f"{report['durationSeconds']}s, {report['turns']} turns, "
        f"{len(report['toolCalls'])} tool calls"
        + (f" - {report['error']}" if report["error"] else ""),
        file=sys.stderr,
    )
    if report["summary"]:
        print(report["summary"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
