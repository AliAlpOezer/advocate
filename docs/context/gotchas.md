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

### The Anthropic escalation tier fails on its first real run
Cause: it has been compiled and unit-tested against a stub, never executed. `langchain-anthropic`
is pinned in `requirements.txt` but **was not installed on the laptop** when
`_anthropic_client()` was written (2026-08-07), so `ChatAnthropic`'s parameter surface was
never introspected. The code deliberately passes only what `llm.py` already proves works
(`model`, `api_key`, `max_tokens`, `timeout`, `max_retries`) and deliberately passes no
effort argument - on Opus 5 effort defaults to `high`, which is what was wanted, so nothing
had to be guessed. Anything added there later is unverified until it runs.
Fix: `pip install -r requirements.txt`, then run one real revision before trusting it. If a
parameter is rejected, check it against the `claude-api` skill rather than the model's
training prior. Do not add `temperature`, `top_p`, `top_k` or `budget_tokens` - Opus 5
returns 400 for all four.

### A free OpenRouter route returns empty or reasoning-only content instead of an answer
Cause: **not the model ignoring instructions** - that is what this entry used to say and
it was wrong. Measured 2026-08-07 by replaying a failing request: `finish_reason: "error"`
inside an HTTP 200, all completion tokens spent on reasoning, no content, no tool call.
The provider fails mid-generation and delivers the failure in a successful response, so a
client checking only the status sees a model that declined to work.
Fix: treat `finish_reason == "error"`, or a reply with neither content nor tool calls, as
a provider failure and fail over. `apply/providers.py` does; `extract.py` does not - its
3 retries are spent on a provider that already failed rather than on a different one.

### A drafting stage runs many turns and writes nothing
Cause: usually the entry above. Read `apply/state/draft-reports/<slug>-<ts>.json` first -
`stages[]` names the stage that stopped and what was wrong with the folder, `attempts[]`
names every provider and key tried.
Fix: do **not** force the call with `tool_choice`. Tried 2026-08-07; it corrupts the
argument on `nemotron-3-ultra` - `<br>` instead of newlines, truncated at 8,192 chars.

### A drafting turn runs far longer than the configured client timeout
Cause: `ChatOpenAI(timeout=...)` is an HTTP read timeout, not a wall clock, and any byte
on the socket resets it. Measured: 20+ minutes against a 600s client; 53,893s once.
Fix: `ADVOCATE_TURN_TIMEOUT_SECONDS` (default 900) is enforced by the chain on a daemon
thread. Do not raise the driver's `APPLY_DRAFT_TIMEOUT_SECONDS` instead - that kills
every stage at once rather than failing one over.

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
