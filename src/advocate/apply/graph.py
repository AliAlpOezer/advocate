"""The drafting pipeline: four short conversations and one deterministic render.

    START -> analyse -> draft_cv -> draft_letter -> claims -> render -> END

Each drafting node runs its own bounded agent/tools loop, and that loop's exit
condition is a filesystem check rather than the model saying it is done. There is
no `finish` tool any more: two runs on 2026-08-06 proved the model will happily
narrate its way past a job it has not done, and the previous harness before that
proved an exit code will happily agree with it.

What the split buys, beyond finishing:

  - **A failure names a stage.** "the loop stopped after 6 turns" becomes
    "draft_letter never wrote the file", which is actionable from the journal
    line alone.
  - **A retry resumes.** A stage whose `problems()` are already empty when it is
    entered is skipped without a model call, so attempt 2 of a draft that got as
    far as the CV starts at the cover letter. `APPLY_DRAFT_MAX_ATTEMPTS` stops
    meaning "do the whole thing again".
  - **Every re-entry to the model is concrete.** The nudge is computed from the
    folder - the missing file, the leftover marker, the em dash - so a model that
    got it nearly right is told the line rather than asked to try harder.

Termination inside a stage, in priority order:
  1. the stage's problems are gone -> done, and the run moves on immediately
  2. the stage's turn cap is reached -> the stage failed, and the pipeline stops
  3. otherwise -> nudged with what is still wrong, then back to the model
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from advocate.apply.stages import DRAFTING_STAGES, Application, Stage
from advocate.apply.state import DraftState, StageState
from advocate.apply.tools import render_documents, tools_for

# Every stage is one tool call's worth of work. A stage still going after this
# many assistant turns is stuck rather than slow, and the turns are the expensive
# part - each one re-sends the whole preloaded corpus.
DEFAULT_STAGE_TURNS = 5


def _nudge_text(stage: Stage, problems: list[str], tool: str) -> str:
    lines = "\n".join(f"  - {p}" for p in problems)
    return (
        f"Stage '{stage.name}' is not finished. Checked on disk just now:\n{lines}\n\n"
        f"Fix it with a {tool} call now. Do not reply with prose - a reply with no tool "
        f"call changes nothing and the stage cannot end until the file is right."
    )


def build_stage_graph(stage: Stage, chat, app: Application, tools: list, sink: list[dict],
                      max_turns: int, log=lambda _msg: None):
    """The agent/tools loop for one stage, with a filesystem check as its exit."""
    by_name = {t.name: t for t in tools}
    write_tool = "write_document" if stage.writer == "document" else "write_file"

    def agent(state: StageState) -> dict:
        turn = state.get("turns", 0) + 1
        started = time.time()
        reply = chat.invoke(state["messages"], tools)
        # Logged per turn, not per stage. A document turn generates thousands of
        # tokens and a stage can take minutes; the OpenCode lesson was that a
        # silent pipe gets diagnosed as a hang and killed at 15 minutes when it
        # was merely slow.
        names = [c["name"] for c in getattr(reply, "tool_calls", [])]
        # Content length is logged because an empty reply and a chatty one are
        # different failures. An empty one should now be impossible - the chain
        # classifies it as a provider failure and fails over - so seeing one here
        # means that classification has a hole in it.
        text = str(getattr(reply, "content", "") or "")
        log(
            f"{stage.name}: turn {turn} in {round(time.time() - started, 1)}s - "
            + (
                ", ".join(names)
                if names
                else f"no tool call, {len(text)} chars of content"
            )
        )
        # The attempt log lives on the chat object because rotation happens
        # underneath a single logical turn; drain it into state so the run report
        # shows the fallbacks in the order they happened.
        drained, chat.attempts = list(chat.attempts), []
        return {
            "messages": [reply],
            "turns": state.get("turns", 0) + 1,
            "attempts": drained,
        }

    def run_tools(state: StageState) -> dict:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        results = []

        for call in last.tool_calls:
            name = call["name"]
            tool = by_name.get(name)
            if tool is None:
                # Reported to the model rather than raised: an invented tool name,
                # or one belonging to another stage, is something it can correct
                # on the next turn.
                results.append(
                    ToolMessage(
                        content=(
                            f"ERROR: no tool '{name}' in this stage. Available: "
                            f"{', '.join(sorted(by_name))}"
                        ),
                        tool_call_id=call["id"],
                    )
                )
                continue
            try:
                output = tool.invoke(call["args"])
            except Exception as exc:  # noqa: BLE001 - a bad argument must not end the run
                output = f"ERROR: {name} failed: {exc}"
            results.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

        # The sink is populated by the tools themselves as they run, so this
        # captures failed calls too, not just the ones that returned cleanly.
        drained, sink[:] = list(sink), []
        return {"messages": results, "tool_calls": drained}

    def nudge(state: StageState) -> dict:
        return {
            "messages": [
                HumanMessage(content=_nudge_text(stage, stage.problems(app), write_tool))
            ],
            "nudges": state.get("nudges", 0) + 1,
        }

    def _next(state: StageState) -> str:
        if not stage.problems(app):
            # Ending here rather than on another pass through the model is what
            # keeps a finished stage from spending one more turn - and one more
            # copy of the preloaded corpus - on a closing pleasantry.
            return END
        if state.get("turns", 0) >= max_turns:
            return END
        return "nudge"

    def route(state: StageState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return _next(state)

    graph = StateGraph(StageState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("nudge", nudge)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "nudge": "nudge", END: END})
    graph.add_conditional_edges("tools", _next, {"nudge": "nudge", END: END})
    graph.add_edge("nudge", "agent")
    return graph.compile()


def _stage_node(stage: Stage, chat, app: Application, sink: list[dict], system_for,
                max_turns: int | None, log):
    """One pipeline node: skip if already done, otherwise run the stage's loop."""
    # Each stage carries its own cap; the caller's value, when given, overrides
    # every stage at once and exists for debugging a single slow run.
    max_turns = max_turns or stage.max_turns
    tools = tools_for(stage, app, sink)
    sub = build_stage_graph(stage, chat, app, tools, sink, max_turns, log)

    def node(state: DraftState) -> dict:
        started = time.time()
        before = stage.problems(app)
        if not before:
            log(f"{stage.name}: already complete, skipped")
            return {
                "stages": [
                    {
                        "stage": stage.name,
                        "ok": True,
                        "skipped": True,
                        "turns": 0,
                        "seconds": 0.0,
                        "problems": [],
                    }
                ]
            }

        log(f"{stage.name}: starting ({len(before)} thing(s) to do)")
        result = sub.invoke(
            {
                "messages": [
                    SystemMessage(content=system_for(stage)),
                    HumanMessage(content=stage.build_task(app)),
                ],
                "turns": 0,
                "nudges": 0,
            },
            # Each super-step is one node, and a turn costs at most three of them
            # (agent, tools, nudge). The stage's own turn cap is the real bound;
            # this is the backstop for a routing bug.
            {"recursion_limit": max_turns * 3 + 6},
        )

        remaining = stage.problems(app)
        seconds = round(time.time() - started, 1)
        record = {
            "stage": stage.name,
            "ok": not remaining,
            "skipped": False,
            "turns": result.get("turns", 0),
            "nudges": result.get("nudges", 0),
            "seconds": seconds,
            "problems": remaining,
        }
        log(
            f"{stage.name}: {'ok' if not remaining else 'FAILED'} in {seconds}s, "
            f"{record['turns']} turns"
            + (f" - {remaining[0]}" if remaining else "")
        )

        out: dict = {
            "stages": [record],
            "turns": result.get("turns", 0),
            "nudges": result.get("nudges", 0),
            "tool_calls": result.get("tool_calls", []),
            "attempts": result.get("attempts", []),
            "lastMessage": str(getattr(result["messages"][-1], "content", "")),
        }
        if remaining:
            out["failed"] = stage.name
        return out

    return node


def _render_node(app: Application, sink: list[dict], log):
    """Both PDFs, in Python. No model turn, and the last thing the pipeline does."""

    def node(state: DraftState) -> dict:
        started = time.time()
        problems = render_documents(app, sink)
        drained, sink[:] = list(sink), []
        seconds = round(time.time() - started, 1)
        log(f"render: {'ok' if not problems else 'FAILED'} in {seconds}s")
        out: dict = {
            "stages": [
                {
                    "stage": "render",
                    "ok": not problems,
                    "skipped": False,
                    "turns": 0,
                    "seconds": seconds,
                    "problems": problems,
                }
            ],
            "tool_calls": drained,
        }
        if problems:
            out["failed"] = "render"
        return out

    return node


def build_graph(chat, app: Application, sink: list[dict], system_for, *,
                max_turns: int | None = None, stages=DRAFTING_STAGES,
                log=lambda _msg: None):
    """Compile the pipeline. `chat` is a ChainedChat; tools and the system
    prompt are both per stage - `system_for(stage)` returns the corpus that
    stage actually needs, which is not the same for all of them."""
    graph = StateGraph(DraftState)
    for stage in stages:
        graph.add_node(stage.name, _stage_node(stage, chat, app, sink, system_for, max_turns, log))
    graph.add_node("render", _render_node(app, sink, log))

    graph.add_edge(START, stages[0].name)
    successors = [s.name for s in stages[1:]] + ["render"]
    for stage, nxt in zip(stages, successors):
        # A failed stage stops the pipeline. Drafting a cover letter against a CV
        # that was never written produces something that has to be thrown away,
        # and the retry would redo it anyway.
        def _continue(state: DraftState, _nxt=nxt) -> str:
            return END if state.get("failed") else _nxt

        graph.add_conditional_edges(stage.name, _continue, {nxt: nxt, END: END})
    graph.add_edge("render", END)
    return graph.compile()
