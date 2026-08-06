"""State for the drafting subgraph.

Everything the driver needs to judge a run afterwards lives here rather than
being inferred from side effects on disk. That is the specific lesson from the
OpenCode harness this replaces: it reported success for a run that made zero
tool calls, because the only evidence available afterwards was an exit code,
and the exit code lied. `tool_calls` and `attempts` make "the model never did
anything" a value you can read instead of something you deduce from missing
files.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class DraftState(TypedDict, total=False):
    # The conversation. `add_messages` appends and de-duplicates by id, which is
    # what lets a provider rotation resume mid-conversation instead of restarting.
    messages: Annotated[list[AnyMessage], add_messages]

    # Identity of the application being drafted. The slug is the tracking store's
    # primary key, so it is passed in and never derived here.
    slug: str

    # Assistant turns taken. Bounded so a model that loops on a failing tool call
    # cannot run until the driver's timeout.
    turns: int

    # One record per tool invocation: name, arguments, ok, and the error if it
    # failed. Written to the run report for the driver's journal line.
    tool_calls: Annotated[list[dict], operator.add]

    # One line per provider/key tried, in order, with the reason it was abandoned.
    # A fallback is visible rather than silent.
    attempts: Annotated[list[str], operator.add]

    # Set by the `finish` tool. The model declaring itself done is a distinct
    # state from the loop running out of turns, and the driver treats them
    # differently.
    finished: bool
    summary: str

    # Times the loop pushed back on a reply that carried no tool calls.
    nudges: int
