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
Cause: **the chain only ever tries key 1, whatever the key count.** Corrected 2026-08-08;
this entry previously said "two keys is not enough, add the other five" and that was
wrong - all seven were deployed and it changed nothing. Key rotation fires on **429 only**.
A `finish_reason='error'` reply advances the **tier** instead, so the chain spends itself
in four calls and six of seven keys are never tried:

```
openrouter[key 1/7]     nemotron-3-ultra: finish_reason='error' → retry → same → next tier
openrouter-alt[key 1/7] nemotron-3-super: finish_reason='error' → retry → same → next tier
```

Measured on the box 2026-08-07 19:33 (BMW). The run burned **1594s and never edited the
scaffold**; `verify.ts` failed it on all four counts including byte-identical-to-template.
Note the interaction with the entry below: `finish_reason='error'` is *already* recognised
as a provider failure, so the bug is not detection, it is which axis the failure advances.
Fix: **not simply "rotate on error too" - that is the trap.** `providers.py`'s docstring
records a deliberate three-way policy: 429 rotates the key, 5xx/timeout retries once then
advances the *tier*, and 401/403/404/400 abandons the tier without touching another key.
`finish_reason='error'` arrives as an HTTP 200 with a bad body, so it currently lands in
the middle bucket - and the stated reason for that bucket is that "rotating keys against a
saturated upstream just spends the pool to hit the same wall." If this failure is NVIDIA
capacity, the current behaviour is right and burning seven keys is wrong.

**The open question is which it is, and it is settled by experiment, not by reading.** Fire
the same request at key 1 until it returns `finish_reason='error'`, then immediately at key
2. If key 2 succeeds it is per-key and rotation is the fix; if it fails identically it is
upstream and the real fix is a different tier-1 model or a paid rung. Do that before
changing the predicate. `apply-draft.timer` stays disabled either way.

### A link added to the review card vanishes the moment a button is tapped
Cause: two separate Telegram constraints, both found 2026-08-08. `InlineButton` in
`telegram.ts` carries `callback_data` only and **has no `url` field**, so a link cannot be
a button without extending the type. And `handleCallback`'s `editMessage` replaces the
**entire message**, text and keyboard together, with a four-line headline - so the posting
URL and the folder link are both destroyed on decision, which is exactly when "what did I
approve?" starts mattering.
Fix: put links in the card *text* (`parse_mode: "HTML"`, so `<a href>` works), and re-add
them to the post-decision edit. Both done for the F10 folder link. `disable_web_page_preview`
is already true, which is load-bearing for tailnet URLs: Telegram's servers cannot reach
the tailnet, so a preview attempt would fail silently.

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
