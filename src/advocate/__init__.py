"""Munich AI job-market agent — LangGraph flagship.

A supervisor graph with isolated per-source agents (context isolation), a
map-reduce skill-extraction stage, deterministic roadmap matching, and an LLM
synthesis node. The Python/LangGraph counterpart to the TS AI-SDK spike
(../../spikes/job-agent).

Design philosophy (full write-ups live in the knowledge vault, cross-linked):
- Agent per source = context isolation; the orchestrator never holds raw markup.
- LLM only where it earns it — fetch / parse / tally are deterministic code.
- Map-reduce via `Send`; durable + resumable via the SQLite checkpointer.
- Robust extraction: prompt-for-JSON + Pydantic-validate + retry-then-skip,
  because free routes ignore json_schema (see extract.py).
  -> vault: Concepts/Agents, Concepts/Structured output,
     Patterns/Gotchas/Free LLM routes ignore json_schema

Modules:
  cli      - argparse entry point (`python -m job_agent.cli`)
  config   - settings: provider + model selection, paths
  state    - LangGraph state schema (typed, with list reducers)
  graph    - the supervisor graph (planner -> sources -> extract -> roadmap -> synthesize)
  sources  - public fetchers (arbeitnow + LinkedIn guest); deterministic
  extract  - JD -> normalized skills (prompt + validate + retry-skip)
  skills   - canonical skill vocabulary + Pydantic schema
  roadmap  - market skill -> sprint-roadmap coverage join table
  llm      - provider factory (free OpenRouter default, Claude opt-in)
"""
