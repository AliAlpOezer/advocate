"""State for the drafting pipeline and for one stage's loop.

Everything the driver needs to judge a run afterwards lives here rather than
being inferred from side effects on disk. That is the specific lesson from the
OpenCode harness this replaces: it reported success for a run that made zero
tool calls, because the only evidence available afterwards was an exit code,
and the exit code lied. `tool_calls` and `attempts` make "the model never did
anything" a value you can read instead of something you deduce from missing
files.

Since the split into stages, `stages` is the field to read first. Two runs on
2026-08-06 both ended with "stalled at four tool calls", which was true and told
nobody where. A per-stage record says which conversation stopped and what was
still wrong with the folder when it did.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class StageState(TypedDict, total=False):
    """One stage's conversation. Fresh per stage - that is the whole point of the split."""

    # `add_messages` appends and de-duplicates by id, which is what lets a
    # provider rotation resume mid-conversation instead of restarting.
    messages: Annotated[list[AnyMessage], add_messages]

    # Assistant turns taken in this stage, bounded by the stage's own cap.
    turns: int

    # Times the loop pushed back with a concrete list of what was still wrong.
    nudges: int

    # One record per tool invocation: name, arguments, ok, and the error if it
    # failed. Lifted into the pipeline state when the stage ends.
    tool_calls: Annotated[list[dict], operator.add]

    # One line per provider/key tried, in order, with the reason it was
    # abandoned. A fallback is visible rather than silent.
    attempts: Annotated[list[str], operator.add]


class DraftState(TypedDict, total=False):
    """The pipeline. Accumulates across stages; nothing here is a conversation."""

    # Identity of the application being drafted. The slug is the tracking store's
    # primary key, so it is passed in and never derived here.
    slug: str

    # One record per stage, in order: name, ok, whether it was skipped as already
    # done, turns, seconds, and whatever was still wrong when it ended.
    stages: Annotated[list[dict], operator.add]

    turns: Annotated[int, operator.add]
    nudges: Annotated[int, operator.add]
    tool_calls: Annotated[list[dict], operator.add]
    attempts: Annotated[list[str], operator.add]

    # The name of the first stage that did not finish. Its presence is what stops
    # the pipeline, and it is the one word the journal line needs.
    failed: str

    # The model's last words, for the report. Prose, so it is context for a human
    # reading a failure, never a signal the pipeline acts on.
    lastMessage: str
