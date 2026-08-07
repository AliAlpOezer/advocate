"""Entry point the draft loop calls instead of shelling out to an agent CLI.

    py -m advocate.apply.cli --repo <advocate-data> --slug <folder> \
        --company ... --title ... --url ... --posting-file ... --report <json>

Two contracts matter to the caller, and both exist because the harness this
replaces honoured neither:

  - **The exit code is honest.** Non-zero whenever no application was produced.
    OpenCode exited 0 on a provider stream error, which is what made its whole
    failover chain unreachable and cost two runs on 2026-08-06.
  - **The report is the real signal.** Even on success it records every stage,
    every tool call and every provider fallback, so "the model made zero tool
    calls" is a value in a file rather than something inferred afterwards from an
    empty folder.

Success is not judged here by counting tool calls any more. Each stage decides
for itself by reading its own output back off disk, so this only has to report
which stage stopped and what was still wrong with the folder when it did.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from advocate.apply.graph import build_graph
from advocate.apply.prompt import build_system_prompt
from advocate.apply.providers import ChainedChat, default_chain, openrouter_keys
from advocate.apply.stages import Application


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
    p.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="override every stage's own turn cap (default: each stage decides)",
    )
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
        "stages": [],
        "toolCalls": [],
        "attempts": [],
        "summary": "",
        "error": None,
    }

    def log(message: str) -> None:
        print(f"[draft-agent] {args.slug}: {message}", file=sys.stderr)

    chat: ChainedChat | None = None

    try:
        app = Application(
            repo=repo,
            slug=args.slug,
            company=args.company,
            title=args.title,
            url=args.url,
            posting_file=args.posting_file,
        )
        # Built once each and reused: the corpus is ~86 KB and every stage of
        # every turn re-sends one of them.
        corpus = {
            True: build_system_prompt(repo, skill_dir, include_skill=True),
            False: build_system_prompt(repo, skill_dir, include_skill=False),
        }

        sink: list[dict] = []
        chat = ChainedChat(default_chain())
        pipeline = build_graph(
            chat, app, sink, lambda stage: corpus[stage.needs_skill],
            max_turns=args.max_turns, log=log,
        )

        log(
            f"{len(corpus[True]):,} chars of grounding material preloaded "
            f"({len(corpus[False]):,} for stages that do not need the skill), "
            f"{len(keys)} key(s), chain: {', '.join(t.model for t in chat.tiers)}"
        )

        final = pipeline.invoke(
            {"slug": args.slug, "turns": 0, "nudges": 0},
            # One super-step per node. Five stages plus the conditional edges
            # between them, with room for a routing mistake to surface as a
            # recursion error rather than a hang.
            {"recursion_limit": 50},
        )

        report["turns"] = final.get("turns", 0)
        report["nudges"] = final.get("nudges", 0)
        report["stages"] = final.get("stages", [])
        report["toolCalls"] = final.get("tool_calls", [])
        report["attempts"] = final.get("attempts", [])
        report["lastMessage"] = final.get("lastMessage", "")[:2000]

        # The stage records already carry the verdict. Anything else here would be
        # a second opinion computed from weaker evidence than the one the stage
        # formed by reading its own output back.
        failed = final.get("failed")
        if failed:
            record = next((s for s in report["stages"] if s["stage"] == failed), None)
            problems = "; ".join(record["problems"]) if record else "no detail recorded"
            report["error"] = f"stage '{failed}' did not finish: {problems}"
        else:
            report["ok"] = True
            report["finished"] = True

        report["summary"] = "\n".join(
            f"{s['stage']}: {'skipped, already done' if s.get('skipped') else 'ok' if s['ok'] else 'FAILED'}"
            f" ({s['turns']} turns, {s['seconds']}s)"
            + (f" - {'; '.join(s['problems'])}" if s["problems"] else "")
            for s in report["stages"]
        )

    except Exception as exc:  # noqa: BLE001 - the report is the contract, not the traceback
        report["error"] = f"{type(exc).__name__}: {exc}"
        # The chain drains its attempt log into graph state on a *successful*
        # turn, so a run that died inside the chain would otherwise report an
        # empty `attempts` while the whole story sat on the chat object.
        report["attempts"] = report["attempts"] or list(chat.attempts if chat else [])
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        report["durationSeconds"] = round(time.time() - started, 1)
        if args.report:
            out = Path(args.report)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for line in report["attempts"]:
        log(line)
    log(
        f"{'ok' if report['ok'] else 'FAILED'} in {report['durationSeconds']}s, "
        f"{report['turns']} turns, {len(report['toolCalls'])} tool calls"
        + (f" - {report['error']}" if report["error"] else "")
    )
    if report["summary"]:
        print(report["summary"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
