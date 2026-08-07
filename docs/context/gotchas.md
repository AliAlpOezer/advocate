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

### Every tier of the drafting chain fails and the draft produces nothing
Cause: **two OpenRouter keys is not enough to run the chain.** Measured on the box
2026-08-07, first real deployed tick: tier 1 `openrouter[key 1/1] nemotron-3-ultra-550b`
rate limited immediately, then `openrouter-alt[key 1/1] nemotron-3-super-120b` returned
`finish_reason='error'` with no content twice, and the run died with every tier exhausted.
The failover logic is correct and did its job; there was simply nothing left to fail over
to. STATUS has long said "the remaining five OpenRouter keys" - this is what their absence
actually costs, which is the whole loop.
Fix: add the other five keys to `/etc/advocate-apply/daemon.env` on `alpiclawd`, or set
`ANTHROPIC_API_KEY` so tier 1 has a paid rung that is not rate limited. Until then the
drafter deploys and runs but cannot finish a document.

### There is no ANTHROPIC_API_KEY to find on this machine, and looking harder will not help
Cause: Claude Code runs on subscription OAuth (`claudeAiOauth`), which is not an API key
and is not interchangeable with one - `ChatAnthropic` needs a real key. Asked on
2026-08-07 to "find the claude token since you are Claude"; there is none to find.
Harvesting the session credential would also be the thing the global rule forbids, because
it converts included subscription tokens into metered billing and breaks the prompt cache.
Fix: create a key at `console.anthropic.com`. It is billed separately from the Claude
subscription, which is what F4 already assumed ("metered API billing, not the
subscription"). Nothing else is blocked on it: without the key a revision degrades to the
free chain with a loud log line, exactly as designed.

### A fix to the document template looks like falsifying a sent application
Cause: `new-application.sh` copied the scaffold from `applications/SSI_Schaefer_Bewerbung`,
a **real, already-sent** application. So the template and the record of what went out were
the same bytes, and correcting the template meant editing history. That is why a stale
Würzburg letterhead survived four applications: everyone who noticed it correctly declined
to rewrite a sent document.
Fix: fixed 2026-08-07 - `applications/_template/` is now the scaffold source and is not a
record of anything. Never point the scaffold back at a real application.

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
