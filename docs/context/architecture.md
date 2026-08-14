# Architecture — job-agent

Budget: 900 tokens. This file answers "where does X live" and "how does X flow" without
the agent having to read the tree. Self-contained — never defer to another context file.

## Shape

A single LangGraph `StateGraph` (built in `graph.py`, compiled + invoked from `cli.py`)
answers "what skills does the Munich AI-Werkstudent market want, and does my roadmap
cover them?" Flow: `START → planner → (Send fan-out) source_arbeitnow / source_linkedin
→ collect (dedup) → (Send fan-out per posting) extract → roadmap (tally+join, reduce) →
synthesize (LLM report) → END`. Fetch/parse/tally nodes are deterministic Python; the LLM
is used only in `extract` (JD → normalized skills) and `synthesize` (final markdown
brief). The graph compiles with a SQLite checkpointer (`checkpoints.sqlite`), so
re-running with the same `--thread` resumes instead of re-fetching. Entry point:
`python -m job_agent.cli "<keywords>" "<location>" <geo_id> [top_n] [--provider] [--model] [--thread]`.

## Map

| Path | Holds |
|---|---|
| `job_agent/cli.py` | argparse entrypoint; builds Config, compiles+invokes the graph with the SQLite checkpointer, prints the report |
| `job_agent/config.py` | `Config` dataclass + `resolve()`: provider/model selection from CLI flags → env (`JOB_AGENT_PROVIDER`/`JOB_AGENT_MODEL`) → default; `assert_key()` checks the right API key is set |
| `job_agent/graph.py` | the StateGraph itself — all node functions, the fan-out `Send` routers, and `format_table()` for the final skill-demand table |
| `job_agent/state.py` | `JobAgentState` TypedDict; parallel-written lists (`raw_jobs`, `skills`) use `operator.add` reducers so concurrent `Send` branches merge instead of clobbering |
| `job_agent/sources.py` | data layer — `fetch_arbeitnow()`, `search_linkedin_guest()`, `fetch_description()`, `dedupe()`, `is_aiish()` filter. Public endpoints only, no auth |
| `job_agent/extract.py` | JD text → `list[ExtractedSkill]` via LLM; hand-rolled JSON-object prompting + Pydantic validation with retries, chosen because free OpenRouter routes ignore schema-constrained structured output |
| `job_agent/skills.py` | `CANONICAL_SKILLS` vocabulary + `ExtractedSkill`/`SkillExtraction` Pydantic schemas — the normalization target every posting is mapped onto |
| `job_agent/roadmap.py` | `ROADMAP_COVERAGE` — hardcoded dict mapping each canonical skill to the user's personal AI-sprint roadmap coverage (covered/partial/gap); `match_roadmap()` joins demand tallies to it; `list_concepts()` does a live glob of an external Markdown-notes vault directory as a freshness signal |
| `job_agent/llm.py` | provider factory (`get_llm`) for OpenRouter vs. Anthropic chat models, and `build_system_prefix()` which adds Anthropic `cache_control` on the stable extraction/synthesis system prompt |

## Boundaries

- Only `sources.py` makes HTTP calls to job boards; only `llm.py`/`extract.py`/`graph.py`
  call the LLM. Nodes in `graph.py` don't reach into `httpx` or LLM clients directly —
  they call functions in `sources.py`/`extract.py`.
- Each source node (`source_arbeitnow`, `source_linkedin`) only ever returns/sees its own
  raw data — the orchestrator state never holds one source's raw HTML while processing
  another (context isolation, stated as a design goal in the README).
- `roadmap.py`'s `ROADMAP_COVERAGE` is deliberately plain Python data, not fetched from
  anywhere — curated by hand as legitimate domain knowledge, not something to RAG over.

## External dependencies

- **arbeitnow.com public JSON API** — no auth. Failure: `httpx` raises on non-2xx;
  uncaught, so the whole run fails if arbeitnow is down (no fallback).
- **LinkedIn guest job-search/job-posting endpoints** (unauthenticated, scraped HTML) —
  on HTTP 429/999 the code logs and backs off (stops paging) rather than evading; on
  other 4xx/5xx it stops and returns what it has so far.
- **OpenRouter** (`openai/gpt-oss-120b:free` default) or **Anthropic** (`claude-sonnet-4-6`
  default) via `langchain-openai`/`langchain-anthropic` — selected by `--provider`/
  `JOB_AGENT_PROVIDER`; requires `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` in `.env`.
  `extract_skills()` retries transient LLM errors 3x then skips that posting (returns `[]`)
  rather than aborting the run; `synthesize` falls back to the deterministic table if the
  synthesis LLM call raises.
- **Local `checkpoints.sqlite`** — LangGraph SqliteSaver checkpointer, gitignored.
