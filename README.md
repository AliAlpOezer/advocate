# 🔎 Munich AI Job-Market Agent — LangGraph flagship

A **supervisor graph** that answers *"what skills does the Munich AI-Werkstudent market want, and does my roadmap cover them?"* from live public data. The Python/LangGraph counterpart to the TS AI-SDK spike (`../spikes/job-agent/`) — same problem, two stacks = a built-in before/after.

## Why it's built this way

- **An agent per source (context isolation).** Each source branch (`source_arbeitnow`, `source_linkedin`) only ever sees its *own* raw HTML/JSON. The orchestrator never holds 6 KB of LinkedIn markup it doesn't need — the model can't get "floated."
- **LLM only where it earns it.** Fetch / parse / tally are deterministic code; the model drives extraction and synthesis. No `fetch()` wrapped in a fake "agent."
- **Map-reduce via `Send`.** Sources fan out in parallel; postings fan out in parallel for extraction; results merge through list reducers.
- **Durable + resumable.** Compiled with a SQLite checkpointer — re-running the same `--thread` resumes from the last checkpoint instead of re-fetching.
- **Hybrid provider.** Free `gpt-oss-120b:free` (OpenRouter) by default; `--provider anthropic` for reliable output + real prompt caching (the stable extraction prefix is marked with `cache_control`).

## Graph

```
START → planner → (Send) ┬ source_arbeitnow ┐
                         └ source_linkedin   ┘→ collect (dedup)
      → (Send) per posting → extract [map] → roadmap [reduce] → synthesize → END
```

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # then add OPENROUTER_API_KEY

# free model (default)
.\.venv\Scripts\python.exe -m job_agent.cli "ai engineer werkstudent" "Munich" 100477049

# Claude path (reliable structured output + measurable prompt caching)
.\.venv\Scripts\python.exe -m job_agent.cli --provider anthropic
```

## Roadmap (next phases)
- **RAG over postings** — embed fetched descriptions (Qdrant + `fastembed`, local/$0) → "which roles want skill X, with citations." (The corpus that actually justifies a vector DB — the 17-note vault fits in a single cached prompt.)
- **Evals** — `pytest` over hand-labeled postings (gold skills vs extracted).
- **Tracing** — LangSmith (env-gated).

## 🔗 Design notes & gotchas (in the knowledge vault)
The durable *why* (and what broke) lives in the vault, linked back to this code:
- [Free LLM routes ignore json_schema](<file:///C:/Users/AliAlpOezer/dev/ai-sprint-vault/Patterns/Gotchas/Free LLM routes ignore json_schema.md>) — why `extract.py` prompts-for-JSON + Pydantic-validates instead of `with_structured_output`
- [Concepts/Agents](<file:///C:/Users/AliAlpOezer/dev/ai-sprint-vault/Concepts/Agents.md>) · [Concepts/Structured output](<file:///C:/Users/AliAlpOezer/dev/ai-sprint-vault/Concepts/Structured output.md>) — the design principles above are written up here
- [Robust LLM extraction pattern](<file:///C:/Users/AliAlpOezer/dev/ai-sprint-vault/Patterns/Snippets/Robust LLM extraction (prompt + validate + retry).md>)
