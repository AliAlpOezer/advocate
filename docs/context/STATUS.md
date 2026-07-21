# Status — job-agent

Last updated: 2026-07-21

## Current focus

<!-- One or two sentences. What is actively being worked on right now. -->
Initial flagship build: LangGraph supervisor graph (planner → fan-out sources → collect
→ fan-out extract → roadmap → synthesize) is implemented end-to-end and runnable via
`python -m job_agent.cli`.

## In flight

<!-- Open PRs / branches. Format: `#12 short-title — waiting on review` -->

## Blocked

<!-- What cannot proceed and what would unblock it. Delete the section if empty. -->

## Next up

<!-- Max 3 items, ordered. Not a backlog — the backlog lives in GitHub issues. -->
1. RAG over fetched postings (Qdrant + fastembed) for "which roles want skill X, with citations."
2. Evals: `pytest` over hand-labeled postings (gold skills vs. extracted).
3. LangSmith tracing (env-gated).

## Recently landed

<!-- Max 3 items. Anything older than a month belongs in git history, not here. -->
- Initial commit: full graph (cli/config/graph/sources/extract/roadmap/llm/state/skills),
  README with architecture + roadmap notes, `.gitignore` hardened to not track secrets
  (`.env`, `checkpoints.sqlite`, `.client_secret.json`).
