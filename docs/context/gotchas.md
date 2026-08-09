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

### A stage reports "already complete, skipped" over a file it never wrote
Cause: the stage's `problems()` compared against the wrong file and could not tell.
`stages.py` held `TEMPLATE_SLUG = "SSI_Schaefer_Bewerbung"` after `verify.ts` moved to
`_template` (2026-08-07 15:14, the entry below). It then compared each scaffold against a
**real sent application** - which exists and differs - so `cv_problems()` came back empty
and `draft_cv` skipped itself over an untouched template. Worse, `template()` returned `""`
for a missing file, making the comparison silently false: the guard said "no problem"
exactly when it had lost the ability to check. `verify.ts` caught it an hour later; nothing
upstream did. The suite could not - `make_repo` builds its template dir *from* the constant
under test, so it agrees with any value.
Fix: fixed 2026-08-08 (`065b018`), and the general rule is the point. **A guard that cannot
perform its check must raise, never return a falsy sentinel.** When two components encode
the same fact, pin one to a literal in a test - a fixture derived from the constant cannot
see it drift.

### The `claims` stage fails on every tier with 0 turns and 0 tool calls
Cause: **the free nemotron route cannot deliver a large tool call.** Settled by experiment
2026-08-08 with `scripts/probe_claims_request.py`, which replays the real request. Not the
keys, not capacity, not the reasoning budget, and not the size of the preload:

```
baseline (as the drafter sends it)   0/4 usable turns   finish_reason='error' @ ~130s
reasoning effort=minimal                  failed        154 reasoning tokens then error
reasoning enabled=false                   failed
reasoning max_tokens=1024                 failed        451 reasoning tokens then error
only write_file offered              0/3 usable turns   one truncated mid-JSON @ 12,265 ch
the identical request with NO tools       OK            8,462 tokens, finish='stop', 434s
```

The last line is the whole diagnosis: at full size the route generates 29,180 chars of
prose happily, and dies only when the same content must come back inside a tool call.
Fix: give the stage a route that can - `stages.CLAIMS_MODEL`, tried ahead of the free
chain by `ChainedChat._chain_for`. Do **not** reach for the reasoning knobs; all three
were measured dead here, and nothing is burning a budget (150-450 reasoning tokens, not
thousands).

### "Shrink the request" looks like it fixes claims, and does not
Cause: dropping the Anschreiben body gave **3/3 usable turns and 0/3 that wrote the file** -
all three spent the turn on `list_files`. A probe that counts any tool call as a pass
reports that as fixed. Worse, the premise was false: `claims` is the **smallest** request
in the pipeline, not the largest, and the two stages that succeed are bigger.

```
analyse  92,673    draft_cv 111,999 ok    draft_letter 118,018 ok    claims 85,240 FAILED
```

Both `stages.py` and `prompt.py` asserted claims was the biggest; that wrong belief is what
aimed the first two attempted fixes at nothing. Fix: judge a drafting probe on whether the
**write** happened, not on whether a reply came back.

### A long request from the laptop dies at 2-8 minutes with WinError 10054
Cause: `ConnectionResetError` on non-streaming requests that run long - seen at 137s, 456s
and 470s against three different hosts, while the same request from `alpiclawd` completed in
434s. Something between this laptop and the internet drops an idle-looking socket.
Fix: run long probes on the box, not the laptop. It is not the provider, and retrying from
here just burns the wall clock again.

### The Python suite reports far more tests than it runs
Cause: fourteen of the eighteen tests in `tests/test_draft_pipeline.py` take a `tmp`
fixture that **was never defined anywhere** - no `conftest.py` has ever existed in this
repo. pytest reports that as an ERROR at setup, not a failure, and a summary line reads
past it. "18 Python tests pass" in STATUS was a count of *collected* tests; four ran. The
tests written to catch the TEMPLATE_SLUG drift were among the fourteen that never
executed.
Fix: fixed 2026-08-08 - the fixture is defined in the test file, 21 tests pass and run.
The general rule is the one this repo keeps relearning: **a check that stops being
performed reports the same as a check that passes.** Read the count, not the colour.
Note `pytest` is not installed in the box's venv, so the suite only runs on the laptop.

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

### A draft run looks like it "finished instantly" and the record never advanced
Cause: `apply-draft.service` is a systemd **oneshot**, so while it works its `ActiveState`
is `activating`, not `active`. `systemctl is-active --quiet` returns non-zero for
`activating`, so the obvious watcher - `while systemctl is-active --quiet apply-draft; do
sleep 20; done` - falls through on the first check and reports a finished run seconds after
it started. The log then shows only the `[draft] <slug> (attempt n/3)` line, the record is
still `drafted`, and `draftAttempts` has not moved, which reads exactly like a crash.
Fix: poll `ActiveState` explicitly and treat three states as still-running:
```
while systemctl show -p ActiveState --value apply-draft.service \
      | grep -qE '^(active|activating|deactivating)$'; do sleep 30; done
```
Confirm before believing a failure: `systemctl status apply-draft` will still list the
`python -m advocate.apply.cli` child in its CGroup, with CPU time climbing. Cost on
2026-08-09: one false "the run failed" report. Same silent-success class as the rest of
this file, inverted - here the harness reported failure for a run that was fine.
