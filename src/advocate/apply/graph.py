"""The drafting subgraph: agent <-> tools, with the loop under our own control.

`create_react_agent` would have been three lines. It is not used, for the same
reason this whole module exists: the previous harness failed because its loop
was somebody else's black box, and the failure was only visible as an absence of
files afterwards. Hand-rolling the two nodes costs very little and buys the
things that were missing - a turn counter, a per-call tool record, an explicit
terminal state, and an assistant turn that cannot silently be zero.

Flow:  START -> agent -> (tools -> agent | nudge -> agent)* -> END

Termination, in priority order:
  1. `finish` was called                  -> done, deliberately
  2. the turn cap was reached             -> not done, and the driver retries
  3. the model narrated instead of acting -> nudged back to work with a concrete
                                             list of what is still missing, up to
                                             MAX_NUDGES times, then given up on
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from advocate.apply.state import DraftState

# Generous. A real draft reads the posting and the template, writes two documents,
# strategy.md and claims-used.md, renders two PDFs and re-reads its own output:
# roughly a dozen calls, plus room to recover from a failed render.
MAX_TURNS = 40

# How many times a model that narrates instead of acting gets pushed back.
MAX_NUDGES = 3


def build_graph(llm, tools: list, tool_sink: list[dict], repo: Path):
    """Compile the drafting loop. `llm` is a ChainedChat already bound to `tools`."""
    by_name = {t.name: t for t in tools}

    def agent(state: DraftState) -> dict:
        reply = llm.invoke(state["messages"])
        # The attempt log lives on the chat object because rotation happens
        # underneath a single logical turn; drain it into state so the run report
        # shows the fallbacks in the order they happened.
        drained, llm.attempts = list(llm.attempts), []
        return {
            "messages": [reply],
            "turns": state.get("turns", 0) + 1,
            "attempts": drained,
        }

    def run_tools(state: DraftState) -> dict:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        results, finished, summary = [], False, ""

        for call in last.tool_calls:
            name = call["name"]
            tool = by_name.get(name)
            if tool is None:
                # Reported to the model rather than raised: an invented tool name
                # is something it can correct on the next turn.
                results.append(
                    ToolMessage(content=f"ERROR: no such tool '{name}'", tool_call_id=call["id"])
                )
                continue
            try:
                output = tool.invoke(call["args"])
            except Exception as exc:  # noqa: BLE001 - a bad argument must not end the run
                output = f"ERROR: {name} failed: {exc}"
            if name == "finish":
                finished = True
                summary = str(call["args"].get("summary", ""))
            results.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

        # The sink is populated by the tools themselves as they run, so this
        # captures failed calls too, not just the ones that returned cleanly.
        drained, tool_sink[:] = list(tool_sink), []
        out: dict = {"messages": results, "tool_calls": drained}
        if finished:
            out["finished"] = True
            out["summary"] = summary
        return out

    def nudge(state: DraftState) -> dict:
        """Answer a model that stopped to narrate instead of finishing.

        Measured on the first LangGraph run, 2026-08-06: the model read the
        posting and both templates, wrote a correct strategy.md, then replied
        with prose and stopped. Treating a tool-call-free reply as completion
        threw away a run that was three quarters done.

        The remedy is only available because the loop is ours: the driver
        already knows mechanically what is missing, so the nudge is a concrete
        checklist rather than "please continue". A model that has genuinely
        finished sees an empty list and calls finish.
        """
        folder = repo / "applications" / state["slug"]
        expected = ["Lebenslauf_Ali_Alp_Oezer", "Anschreiben_Ali_Alp_Oezer"]
        missing = [f"{name}.pdf" for name in expected if not (folder / f"{name}.pdf").is_file()]
        for name in ("strategy.md", "claims-used.md"):
            if not (folder / name).is_file():
                missing.append(name)

        return {
            "messages": [
                HumanMessage(
                    content=(
                        "You stopped without calling finish, so the run is not complete. "
                        "Do not reply with prose - use tools.\n\n"
                        + (
                            "Still missing from applications/"
                            f"{state['slug']}/: {', '.join(missing)}.\n"
                            "Write what is missing, render both documents with render_pdf, "
                            "then call finish."
                            if missing
                            else "Everything expected is on disk. Read your two documents back "
                            "one last time to confirm no template text survived, then call finish."
                        )
                    )
                )
            ],
            "nudges": state.get("nudges", 0) + 1,
        }

    def route(state: DraftState) -> str:
        if state.get("finished"):
            return END
        if state.get("turns", 0) >= MAX_TURNS:
            return END
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        # No tool calls and no finish: the model narrated. Push back, but bounded -
        # a model that will not act is a failed draft, not an infinite loop.
        if state.get("nudges", 0) < MAX_NUDGES:
            return "nudge"
        return END

    def after_tools(state: DraftState) -> str:
        # `finish` ends the run here rather than on the next pass through `route`.
        # Going back to the agent first would spend one more provider call - and a
        # whole preloaded-context turn - after the work is already done, and would
        # leave a stray assistant message after the closing summary.
        return END if state.get("finished") else "agent"

    graph = StateGraph(DraftState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("nudge", nudge)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "nudge": "nudge", END: END})
    graph.add_edge("nudge", "agent")
    graph.add_conditional_edges("tools", after_tools, {"agent": "agent", END: END})
    return graph.compile()
