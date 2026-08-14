"""Replay the real `claims` request and find out which lever makes it work.

    py scripts/probe_claims_request.py --repo /srv/advocate-data --slug BMW_...
    py scripts/probe_claims_request.py --repo ... --slug ... --only baseline,reasoning-off

Why this exists. On 2026-08-08 the BMW draft got both documents written and then
`claims` FAILED after 2,407s: every tier, 0 turns, 0 tool calls. The key-rotation
probe was re-run minutes later against the same model on the same key and
returned 7/7 OK, so the failure is **request shape**, not the key and not upstream
capacity - a short request succeeds while this one dies.

`claims` is the largest request in the pipeline: ~66k chars of preloaded corpus
plus both finished documents, asking for a long generation, on a model that
reasons in the open. Three candidate fixes were proposed, cheapest first: cap or
disable the reasoning budget, shrink the preload, or move the stage to the paid
rung. Which one to spend is a fact, and this measures it rather than arguing it.

Each variant is the **real** request - the same system prompt `prompt.py` builds,
the same task `stages.py` builds, the same tool schemas `tools.py` binds - with
exactly one thing changed. Sent over raw HTTP rather than through ChainedChat so
the wire body is visible and `reasoning` can be set to shapes LangChain does not
model.

Sequential and one key throughout. Concurrency would manufacture the upstream
saturation that a130157 already ruled out, and rotating keys would reintroduce
the variable this is holding still.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BASE = "https://openrouter.ai/api/v1"
TIER1 = os.environ.get("ADVOCATE_DRAFT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

# What each variant changes about the request, and the lever it is testing. The
# first is the control: if it does not fail, nothing below it means anything.
VARIANTS: dict[str, str] = {
    "baseline": "the request exactly as the drafter sends it today (control - expected to FAIL)",
    "effort-minimal": "lever 1: reasoning.effort=minimal",
    "reasoning-off": "lever 1: reasoning.enabled=false",
    "reasoning-cap": "lever 1: reasoning.max_tokens=1024",
    "cv-only": "lever 2: same request with the Anschreiben body dropped from the task",
    "write-only": "lever 4: full request, but only the write_file tool is offered",
    # Neither of the next two is a shippable fix. They are here to locate the
    # boundary, because "shrink the preload" is only worth designing if size is
    # what the provider is actually dying on.
    "no-corpus": "DIAGNOSTIC: header only, dossier and claims.yaml dropped (~85k -> ~22k chars)",
    "no-tools": "DIAGNOSTIC: the full request with no tools, so prose is a pass",
}


def build_request(repo: Path, slug: str, skill_dir: Path | None):
    """The real system prompt, the real task, the real tool schemas.

    Imported from the package rather than reconstructed, so a probe cannot pass
    while the drafter fails on a difference between the two. That is the failure
    mode `make_repo` had in the TEMPLATE_SLUG drift: a fixture that agrees with
    whatever the code says cannot see the code being wrong.
    """
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from advocate.apply.prompt import build_system_prompt
    from advocate.apply.stages import DRAFTING_STAGES, Application
    from advocate.apply.tools import tools_for

    stage = next(s for s in DRAFTING_STAGES if s.name == "claims")
    app = Application(
        repo=repo, slug=slug, company="", title="", url="",
        # The claims task does not read the posting, so a placeholder here would
        # only matter if that changed. Point it at the real one anyway.
        posting_file=f"applications/{slug}/posting.md",
    )
    system = build_system_prompt(
        repo, skill_dir or repo / ".claude" / "skills" / "cv-drafter",
        include_skill=stage.needs_skill,
    )
    task = stage.task_for(app)
    tools = [convert_to_openai_tool(t) for t in tools_for(stage, app, [])]
    return app, stage, system, task, tools


def body_for(variant: str, system: str, task: str, tools: list, model: str) -> dict:
    """One wire body: the request, with exactly one thing changed."""
    if variant == "cv-only":
        # The task carries both finished documents. Dropping one halves the
        # volatile half of the request without touching the corpus, which is
        # what says whether size alone is the discriminator.
        marker = "=== the finished Anschreiben body ==="
        task = task.split(marker)[0].rstrip() + "\n"
    if variant == "no-corpus":
        # Everything from the first document separator onwards is the preloaded
        # corpus. Cutting there leaves the header's standing instructions intact,
        # so the only variable is the volume of evidence.
        system = system.split("=" * 70)[0].rstrip() + "\n"

    if variant == "write-only":
        # `claims` has no reason to read anything: the corpus is in the system
        # prompt and both finished documents are in the task. The two passing
        # tool-bound samples in the first run both spent their turn on a
        # `list_files` or `read_file` rather than on the write, which is the
        # behaviour this removes the option for.
        tools = [t for t in tools if t["function"]["name"] == "write_file"]

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ],
        "tools": tools,
        "temperature": 0.2,
    }
    if variant == "no-tools":
        body.pop("tools")
    if variant == "effort-minimal":
        body["reasoning"] = {"effort": "minimal"}
    elif variant == "reasoning-off":
        body["reasoning"] = {"enabled": False}
    elif variant == "reasoning-cap":
        body["reasoning"] = {"max_tokens": 1024}
    return body


def send(body: dict, key: str, timeout: int, base: str = BASE, *,
         prose_is_ok: bool = False) -> dict:
    """One request. Returns a verdict dict; never raises."""
    started = time.time()
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions", data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "verdict": f"HTTP {err.code}", "detail": detail,
                "seconds": round(time.time() - started, 1)}
    except Exception as err:  # noqa: BLE001 - a probe reports, it does not raise
        return {"ok": False, "verdict": f"{type(err).__name__}", "detail": f"{err}"[:300],
                "seconds": round(time.time() - started, 1)}

    seconds = round(time.time() - started, 1)
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    calls = message.get("tool_calls") or []
    content = message.get("content") or ""
    reasoning = message.get("reasoning") or ""
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}

    out = {
        "seconds": seconds,
        "finish": finish,
        "content": content,
        "firstArgs": ((calls[0].get("function") or {}).get("arguments") if calls else ""),
        "toolCalls": [c.get("function", {}).get("name") for c in calls],
        "contentChars": len(content),
        "reasoningChars": len(reasoning),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "reasoningTokens": details.get("reasoning_tokens"),
        "error": (payload.get("error") or {}).get("message"),
    }

    # The drafter's own definition of a usable turn, applied identically here:
    # a 200 with no tool call and no content is a provider failure, not a turn.
    if finish == "error" or (not calls and not content.strip()):
        out["ok"] = False
        out["verdict"] = f"UNUSABLE (finish_reason={finish!r}, {len(calls)} tool calls)"
        return out

    # `claims` is a write_file stage. Content without the call does not write the
    # file, so it is not a pass - it is the stage narrating instead of working.
    # The exception is the no-tools diagnostic, where prose is the only thing on
    # offer and the question being asked is whether the route answers at all.
    if not calls and prose_is_ok:
        out["ok"] = True
        out["verdict"] = f"OK, prose ({len(content)} chars, finish={finish!r})"
        return out
    if not calls:
        out["ok"] = False
        out["verdict"] = f"NO TOOL CALL ({len(content)} chars of prose, finish={finish!r})"
        return out

    # Two different questions, and conflating them flatters the result. The chain
    # only needs a *usable turn* to keep going - any tool call will do, and a
    # `list_files` is enough to stop the stage dying at 0 turns. Whether the stage
    # actually finishes needs the write. Report both; the first is what the
    # failure being chased is about.
    first = calls[0].get("function", {}) or {}
    args = first.get("arguments") or ""
    wrote = any((c.get("function") or {}).get("name") == "write_file" for c in calls)
    out["ok"] = True
    out["wrote"] = wrote
    out["argChars"] = len(args)
    out["verdict"] = (
        f"{'WROTE' if wrote else 'usable turn'} ({first.get('name')}, {len(args)} chars of argument)"
    )
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, help="the advocate-data checkout")
    p.add_argument("--slug", required=True, help="an application with both documents drafted")
    p.add_argument("--skill-dir")
    p.add_argument("--only", help=f"comma-separated subset of: {', '.join(VARIANTS)}")
    p.add_argument("--repeat", type=int, default=1,
                   help="samples per variant. One sample cannot tell a size threshold from a "
                        "flaky route, and this failure has already been misdiagnosed twice by "
                        "reading a single run")
    p.add_argument("--base-url", default=BASE,
                   help="an OpenAI-compatible endpoint. Anything that speaks this shape can be "
                        "compared against the free route on the identical request")
    p.add_argument("--model", default=TIER1)
    p.add_argument("--key-env", default="OPENROUTER_API_KEY",
                   help="the environment variable holding the key for --base-url")
    p.add_argument("--env-file",
                   help="a .env to load first, so a key that lives on the laptop never has to be "
                        "copied to the box to be measured")
    p.add_argument("--save", help="directory to write each reply's content into, so a variant "
                                  "that passes can be judged on what it actually produced "
                                  "rather than on the fact that it replied")
    p.add_argument("--timeout", type=int, default=660,
                   help="per request. The measured failures took ~600s each, so a shorter "
                        "bound turns the thing being measured into a timeout")
    args = p.parse_args()

    if args.env_file:
        for line in Path(args.env_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))

    key = os.environ.get(args.key_env)
    if not key:
        print(f"No {args.key_env}. On the box: set -a; . /etc/advocate-apply/daemon.env; set +a"
              f"\nOr pass --env-file <path to a .env holding it>.")
        return 2

    repo = Path(args.repo).resolve()
    app, stage, system, task, tools = build_request(
        repo, args.slug, Path(args.skill_dir) if args.skill_dir else None
    )
    from advocate.apply.stages import CV, LETTER

    for name in (CV, LETTER):
        if not (app.folder / name).is_file():
            print(f"{args.slug} has no {name}. This replays the request `claims` makes *after* "
                  f"both documents are drafted; without them it is a different request.")
            return 2

    chosen = [v.strip() for v in args.only.split(",")] if args.only else list(VARIANTS)
    unknown = [v for v in chosen if v not in VARIANTS]
    if unknown:
        print(f"unknown variant(s): {', '.join(unknown)}. Known: {', '.join(VARIANTS)}")
        return 2

    print(f"model  : {args.model}")
    print(f"host   : {args.base_url}")
    print(f"system : {len(system):,} chars   task: {len(task):,} chars   "
          f"tools: {', '.join(t['function']['name'] for t in tools)}")
    print(f"key    : {args.key_env} (one key throughout - this holds the key variable still)\n",
          flush=True)

    results: dict[str, dict] = {}
    for variant in chosen:
        body = body_for(variant, system, task, tools, args.model)
        chars = sum(len(m["content"]) for m in body["messages"])
        print(f"  {variant:<16} {VARIANTS[variant]}")
        print(f"  {'':<16} sending {chars:,} chars"
              + (f", {args.repeat} samples" if args.repeat > 1 else "") + " ...", flush=True)

        samples = []
        for n in range(args.repeat):
            result = send(body, key, args.timeout, args.base_url,
                          prose_is_ok=variant == "no-tools")
            samples.append(result)
            usage = (f"{result.get('promptTokens')} in / {result.get('completionTokens')} out"
                     f" ({result.get('reasoningTokens')} reasoning)"
                     if result.get("promptTokens") is not None else "no usage reported")
            if args.save:
                saved = Path(args.save)
                saved.mkdir(parents=True, exist_ok=True)
                text = result.get("firstArgs") or result.get("content") or ""
                if text:
                    (saved / f"{variant}-{n + 1}.txt").write_text(text, encoding="utf-8")
            label = f"{n + 1}/{args.repeat}" if args.repeat > 1 else "->"
            print(f"  {'':<16} {label} {result['verdict']}  [{result['seconds']}s, {usage}]")
            if result.get("error"):
                print(f"  {'':<16}    error: {result['error'][:200]}")
            if result.get("detail"):
                print(f"  {'':<16}    detail: {result['detail'][:200]}")
            sys.stdout.flush()

        usable = sum(1 for s in samples if s.get("ok"))
        wrote = sum(1 for s in samples if s.get("wrote"))
        results[variant] = {
            "ok": usable > 0,
            "usable": usable,
            "wrote": wrote,
            "samples": len(samples),
            "verdict": (f"{usable}/{len(samples)} usable turns, {wrote} wrote the file"
                        if args.repeat > 1 else samples[0]["verdict"]),
        }
        if args.repeat > 1:
            print(f"  {'':<16} => {results[variant]['verdict']}")
        print(flush=True)

    print("=" * 70)
    control = results.get("baseline")
    diagnostic = {"no-corpus", "no-tools"}
    # A lever has to beat the control, not merely produce one good sample. With
    # repeats that means a majority; with a single sample it is the only thing on
    # offer and the verdict says so.
    def carried(r: dict) -> bool:
        return r.get("usable", 0) * 2 > r.get("samples", 1)

    winners = [v for v, r in results.items()
               if v != "baseline" and v not in diagnostic and carried(r)]
    passed_diagnostics = [v for v, r in results.items() if v in diagnostic and carried(r)]

    if control and carried(control):
        print("NOT REPRODUCED. The request the drafter sends succeeded here, so this run "
              "cannot classify anything. Do not change the request on this evidence - "
              "re-run while the drafter is actually failing.")
    elif not control:
        print("No control in this run (baseline not selected), so a passing variant is not "
              "yet evidence that the lever is what fixed it. Re-run with baseline included.")
    elif winners:
        print(f"FIXED BY: {', '.join(winners)}")
        print("The control failed and these did not, so the lever each one names is the "
              "cheapest thing that makes `claims` work. Apply the leftmost and re-run BMW.")
    else:
        print("NO SHIPPABLE LEVER. The control failed and every candidate failed with it, so "
              "neither the reasoning budget nor dropping one document is the fix.")

    if passed_diagnostics:
        print(f"\nDiagnostics that passed: {', '.join(passed_diagnostics)}. These are not "
              f"fixes - they say where the boundary is:")
        if "no-corpus" in passed_diagnostics:
            print("  - no-corpus passed, so the route dies on the *volume* of the request. "
                  "Shrinking the preload is the lever, and it has to be a real cut, not the "
                  "one document `cv-only` drops.")
        if "no-tools" in passed_diagnostics:
            print("  - no-tools passed at full size, so volume alone is survivable and it is "
                  "tool-calling at this context length that breaks. Shrinking may not be "
                  "enough; the honest fix is a route that can do both.")

    print("\nper-variant, for the record:")
    for variant, result in results.items():
        print(f"  {variant:<16} {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
