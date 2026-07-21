# Gotchas — job-agent

Budget: 600 tokens. Traps that cost someone real time. Routed to first on any "it's
broken / slow / weird" task, so lead with the **symptom** — that's what the agent is
pattern-matching against.

## Template

```
### <symptom as it is actually observed>
Cause: <what is really happening>
Fix: <what to do>
```

<!-- Entries below. Delete one the moment the underlying cause is fixed for good —
     a stale gotcha sends agents down a dead path with full confidence. -->

### `extract_skills()` returns `[]` for many/all postings on the default (free) provider
Cause: free OpenRouter routes (`openai/gpt-oss-120b:free`) sometimes ignore instructions
and return reasoning-only or empty content instead of the requested JSON; `extract.py`
retries 3x then gives up and returns `[]` for that posting rather than failing the run.
Fix: this is expected/handled behavior, not a bug to "fix" in extract.py. Run with
`--provider anthropic` for reliable output if you need consistent extraction.

### Re-running with the same query silently returns stale/incomplete results
Cause: `cli.py` derives `thread_id` from `keywords|location|geo_id` (or `--thread`) and
compiles with a SQLite checkpointer (`checkpoints.sqlite`); LangGraph resumes that
thread from its last checkpoint instead of re-fetching/re-extracting.
Fix: pass a different `--thread` value (or delete `checkpoints.sqlite`) to force a
clean run.

### Console crashes on emoji/report output (`UnicodeEncodeError`) when run outside the CLI's own entrypoint
Cause: Windows consoles default to cp1252; `cli.py` forces `sys.stdout.reconfigure
(encoding="utf-8")` at import time to work around it. If code that prints the report
(icons `✅⚠️❌`, `🔎`, etc.) runs through a path that skips that reconfigure, it will
crash on Windows.
Fix: keep the UTF-8 reconfigure in `cli.py`'s entrypoint; don't strip it.

### LinkedIn results stop partway through / come back short
Cause: `search_linkedin_guest()` hits the unauthenticated guest endpoint; on HTTP
429/999 it logs a warning and breaks out of the paging loop rather than retrying or
rotating UA/proxy — deliberate: public endpoints only, back off rather than evade.
Fix: expected behavior, not a retryable bug. Reduce `pages`/frequency if it happens often.
