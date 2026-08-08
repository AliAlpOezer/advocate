# Status — advocate

Last updated: 2026-08-08

## Read this first — the claims blocker, settled

**`claims` failed because the free nemotron route cannot deliver a large tool call.**
Settled 2026-08-08 by replaying the real request (`scripts/probe_claims_request.py`), not
by reasoning. The full evidence table is in `gotchas.md`; the short form is that the
identical 85,240-char request succeeds with the tools removed (8,462 tokens, `finish='stop'`)
and returns `finish_reason='error'` 0/4 times with them.

**All three fixes proposed on the previous line were measured and are wrong.** Capping or
disabling the reasoning budget: dead, three ways, and nothing was burning a budget in the
first place (150-450 reasoning tokens, not thousands). Shrinking the 65,987-char preload:
dead, and its premise was false - `claims` is the *smallest* request in the pipeline at
85,240 chars, while `draft_letter` succeeds at 118,018. Moving to the paid rung: still
correct in spirit, but every paid path is blocked on Alp (see below).

**Shipped (`97954af`, deployed to the box): a stage may name its own route.**
`stages.CLAIMS_MODEL` is tried ahead of the free chain; the drafting stages keep the
default because they work and their German has been approved. Rationale in `decisions.md`.

**Confirmed end to end on the box, 2026-08-08 15:53 UTC. The loop has sent its first
review card.** BMW ran with `CLAIMS_MODEL=poolside/laguna-s-2.1:free`:

```
analyse/draft_cv/draft_letter: skipped (already correct)
claims: ok 1109.3s, 3 turns, write_file on turn 3      render: ok 1.0s
```

`claims-used.md` is 200 lines / 27,094 bytes, both PDFs rendered, and the record moved to
`pending_review` with `reviewNotifiedAt=2026-08-08T15:53:46.854Z` and an `artifactHash`.
That closes the "no review card has ever been sent" gap below, and it exercises the
PDF-attachment path in production for the first time. **Judge the card itself before
trusting the German** - nothing has graded this map yet.

Three turns, not one: the model spends its first turns on `list_files`/`read_file` before
writing. That is fine - the stage allows five - but it means a probe that stops after one
turn cannot tell this route from a broken one.

**The Alibaba plan key is deployed on the box (2026-08-08) and is NOT yet proven for this
stage.** `/etc/advocate-apply/daemon.env` now carries `ALIBABA_API_KEY` (the plan-specific
secret) and `ALIBABA_BASE_URL`. Auth and URL are verified. But the real claims request
against `qwen3.8-max` **timed out at 660s from the box** - not a 403, not the laptop's
network, just no reply. A small tool-bound request to the same model answers in seconds, so
the model works and the long generation is what does not fit in 660s.

Do not wire it in until it is measured. The next two commands, in order:

```
ssh alpiclawd 'cd /srv/advocate && set -a && . /etc/advocate-apply/daemon.env && set +a && \
  .venv/bin/python -u scripts/probe_claims_request.py --repo /srv/advocate-data \
  --slug BMW_Group_Junior_Agentic_AI_Engineer_limited_Bewerbung \
  --base-url "$ALIBABA_BASE_URL" --model qwen3.8-max --key-env ALIBABA_API_KEY \
  --only baseline --timeout 900'          # 900 matches the drafter's own turn bound
# then the same with --model deepseek-v4-pro
```

For scale: laguna takes 1,109s over three turns and works, so "slow" is normal here and 660s
was simply the wrong bound to judge by.

**Trap, cost 20 minutes:** writing `daemon.env` from Windows inserts CRLF, and `\r` silently
corrupts both the key and the URL (`.../v1\r/chat/completions`). Backup of the pre-edit file
is at `alpiclawd:/root/daemon.env.bak-2026-08-08`. Strip with `sed -i 's/\r$//'`.

`~/.claude/settings.json` now allows `Bash(ssh alpiclawd *)` and `Bash(scp * alpiclawd:*)`.
These are **prefix** matches, so a command must literally start with `ssh`/`scp` - piping
into ssh does not match and is still refused by the auto-mode classifier.

**Why bother: 1,109s for one stage is slow and the free route has no headroom.**
`ALIBABA_PLAN_SPESIFIC_SECRET` against
`https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` reaches **seven
models, all of which tool-call**, including `qwen3.8-max` and `deepseek-v4-pro`. It was
not wired in because the probe against it could not be completed from the laptop (see the
WinError 10054 gotcha) and the key is not on the box - piping a credential over ssh was
refused by the harness, so **Alp has to place it in `/etc/advocate-apply/daemon.env`
himself.** Once it is there:

```
ADVOCATE_CLAIMS_MODEL=qwen3.8-max          # plus the base URL and key, wired as a tier
```

Note the two Alibaba keys already in the repo `.env` are *not* interchangeable: each is
bound to its own host and returns 401 against the others, and only the plan-specific one
has any entitlement. Table in `decisions.md`.

## The CV rework, asked for 2026-08-08 — three of four rules written

Asks 1-3 are **written into `advocate-data/.claude/skills/cv-drafter/SKILL.md`** and are
uncommitted there pending Alp's review. Note the deploy coupling: the box pulls
`advocate-data` master `--ff-only` every tick, so committing to master ships them to the
live drafter on the next run.

1. **The marathons are bold in every CV.** Done, in Writing craft. It is a markup change,
   not just a directive: they currently sit unemphasised at the tail of the run-on
   `Erfolge` line in `_template`, behind a `·` separator.
2. **A bolder, more self-confident tone throughout.** Done, in Writing craft, framed
   explicitly as *inside* the one law - framing pushes, checkable facts do not move.
3. **A profile section.** Done - a new `## The profile section` in SKILL.md, mandatory and
   rewritten per posting. Two things settled while writing it:
   - **The markup already exists.** `<p class="profil">` at the top of `_template`'s main
     column, unheaded, left accent bar. So the reference PDF
     (`Resume_Project/Ali_Alp_Ozer_Resume.pdf`, section `ÜBER MICH`) is the model for
     register and shape only, *not* layout - it heads the block and right-columns it.
     The template's generic paragraph counts as a template leftover; not rewriting it is
     a drafting failure.
   - **Named concepts belong in this block and nowhere else on the CV**, and naming them
     is the point - MVC-structured frontend, ReAct-structured LangGraph agents, RAG with
     a measured baseline, MCP. Bound by warrant, not by permission: name one where the
     posting makes it load-bearing, cut it where the paragraph does not lose anything.
     Alp's framing is that a parade of patterns reads as someone who has read about them.
     The traceability rule applies as it does everywhere, and is rarely the binding
     constraint - these are patterns he has shipped, and MVC is already explicit in the
     experience bullets of his own CV.

   The ~18 lines of reference wording he pasted never reached either session. **Stop
   asking for them** - the screenshot of the CV supplied the same material.

   **Enforced, not just written.** `verify.ts` gained check 1b plus an exported
   `profileParagraph()`: the CV's `.profil` block must exist, be at least 200 chars, and
   differ from `_template`'s. The whole-file byte check could not catch this - rewrite
   every bullet, leave the profile, and the file is byte-different, so it passed. The
   comparison is on extracted text, so reflowing and adding `<strong>` do not read as a
   change. **26 TypeScript tests pass, was 22.** Checked against all five existing
   applications: BCG, BMW, Temedica and Vodafone all pass; only `SSI_Schaefer` matches the
   template, because `_template` was cut from it. It is already sent and never re-verified.

   `_template` itself was updated in the same pass: marathons bolded, HF certificate added.

**The Hugging Face Agents Course is done - Certificate of Excellence, 2026-08-04.** It was
listed as "in progress" in four places, all now moved to completed: `EVIDENCE_DOSSIER.md`
§6 (and the §7 Hugging Face skill line, which said "certification in progress" and would
have contradicted it), `master_resume_de.md`, `master_resume_en.md`, and `_template`'s
`Zertifikate` block. It is a completed credential and lists as one; it does not upgrade
the HF *skill* line, which is about the Hub, not agents. No public verification URL was
captured - Alp holds the certificate image. Not yet in `claims/claims.yaml`.
4. **Use the Alibaba models now that they are proven.** See `decisions.md` for which key
   reaches what. Requires Alp to put `ALIBABA_PLAN_SPESIFIC_SECRET` and its base URL into
   `/etc/advocate-apply/daemon.env` first; the harness refuses to let an agent pipe a
   credential over ssh. Worth considering for the drafting stages too, not only `claims`
   - but re-read the warning in `decisions.md` about swapping the model that writes the
   documents, and change one thing at a time.

Constraints that still bind any tone change: no em dash anywhere, city only and never a
street address or commute argument, and every factual sentence traceable. `verify.ts` and
`stages.py` both enforce these mechanically and will fail the draft rather than soften it.

**The test suite was never running.** Fourteen of eighteen tests errored on a `tmp` fixture
that was never defined; "18 Python tests pass" counted collected tests and four ran. Fixed
in the same commit - **21 pass and execute**. `pytest` is not installed in the box's venv,
so the suite runs on the laptop only.

## Current focus

**Whole-system architecture accepted 2026-08-07: `three-loop-architecture.md`.** Read it
before touching the hunt, the drafter or anything that sends. It is the routing target for
"how do these fit together" and it supersedes `advocate-system-concept.md`'s component
sketch where they disagree (the knowledge-base and eval designs there are unchanged).

Three loops, one store, one knowledge base; the loops never call each other, they hand
work over by writing a record. Nine findings, three of them defects in what is already
built. Alp settled the three open decisions the same day: portal credentials go to
Postgres and never into `applications/`; the record state machine moves to Postgres when
the submitter is built, artifacts stay in git; and the existing draft→review loop gets
closed before the irreversible send component is added.

**F1, F3 and F4 are built and tested, same day** — approval bound to an artifact
fingerprint, reject split from revise with the reason captured over Telegram, and the
`claude-opus-5` escalation tier with a cache breakpoint on the 85 KB corpus. 16 Python
tests and 9 TypeScript ones pass; `assertSendable` has coverage for the first time.
Detail, including the two silent-success traps found while building it, is in
`three-loop-architecture.md` §Built. **Nothing is deployed** — the box still needs the
venv, the remaining five OpenRouter keys, `ANTHROPIC_API_KEY`, and Bucket 2's chat id.

**Deployed to `alpiclawd` 2026-08-07, and the gate is live.** `apply-bot.service` is
running and polling; `/srv/advocate/.venv` exists with `requirements.txt` installed;
`/etc/advocate-apply/daemon.env` carries the two OpenRouter keys, the venv interpreter and
the queue cap; the Telegram chat id is set (Bucket 2's last gap, closed). Both suites pass
**on the box**: 16 Python, 18 TypeScript.

**The drafter's CV stage was never running. Root-caused and fixed 2026-08-08 (`065b018`).**
Two earlier diagnoses on this line were both wrong, and each was wrong in the same way -
they explained the loudest error in the log rather than the reason no CV existed.

`stages.py` held `TEMPLATE_SLUG = "SSI_Schaefer_Bewerbung"`. `verify.ts` moved to a
dedicated `_template` on 2026-08-07 15:14 and this copy did not follow. The two sides then
disagreed in the worst possible direction: the Python guard compared each new scaffold
against *a real sent application*, which exists and differs, so `cv_problems()` returned
empty and `draft_cv` skipped itself as "already complete" over an untouched template.

Measured, not reasoned. BMW attempt 2 on 2026-08-08 09:03:

```
analyse: skipped   draft_cv: skipped   draft_letter: skipped   claims: ok 330s   render: ok
```

The provider chain was **healthy** on that run - no tier exhaustion, no `finish_reason='error'`.
It still failed, because the stage that writes the CV was never asked to run. It then spent
330s writing a 254-line grounding record for a CV that was still the scaffold, and rendered
that scaffold into a 126 KB PDF. `verify.ts` caught all of it; nothing upstream did.

The fix is two lines and one principle: `TEMPLATE_SLUG = "_template"`, and `template()`
now **raises instead of returning `""`** when the file is missing. That empty string is
what let the drift hide - it made the byte-identity comparison silently false, so the guard
reported "no problem" at exactly the moment it stopped being able to check. Same
silent-success class as the two traps already recorded in §Built.

The suite could not have caught it: `make_repo` builds its template dir at
`applications/<TEMPLATE_SLUG>/`, so it agrees with the constant whatever it says. The new
test pins the literal, which is the one thing a fixture cannot fake. **18 Python tests pass,
was 16.**

**Blast radius is exactly one application**, and the timeline proves it: Vodafone drafted
11:21 (constant still correct), `_template` landed 15:14, BMW 19:33 was the first run to
hit the drift. Vodafone's and Temedica's CVs re-check clean under the fix - no false
positives.

**Key rotation is a real but separate defect, still unfixed and now un-blamed.** It fires
on 429 only, so `finish_reason='error'` walks the tiers and exhausts the chain in four
calls with six of seven keys untried. That is worth fixing on its own merits; it was never
the reason the drafter produced nothing.

`scripts/probe_key_rotation.py` was run on the box 2026-08-08 against both tiers and
returned **INCONCLUSIVE twice - 14/14 key-model pairs OK**. The 2026-08-07 19:33 failure
was transient upstream capacity, since recovered. Do not change the rotation predicate on
this evidence; re-run the probe while the drafter is actually failing.

**Measured in passing: nemotron-3 reasons in the open by default.** With `max_tokens: 16`,
5 of 7 keys on tier 2 returned the model's scratchpad (`'The user asks: "Repl'`) instead of
the requested word. Same failure mode already recorded for the hunt's fit gate, now
confirmed on both drafting models. It is a live candidate cause for any future
`finish_reason='error'`-with-no-tool-call: an open-reasoning model can burn its budget
thinking and never reach the tool call.

**`apply-draft.timer` stays NOT enabled** until BMW completes one clean end-to-end run by
hand.

**F2 was answered by a button, not built.** A dead listing is now 🚫 Listing gone on the
review card (plus `/gone <slug>`), which drops the record to `withdrawn`. Component 1b is
struck. Rationale and the accepted tradeoff are in `three-loop-architecture.md` §F2.

**F9's queue cap is built**: the drafter skips its tick at 3 pending reviews, resume path
included.

**F10's artifact viewer is built 2026-08-08, not yet deployed.** Component 6: a read-only
`viewer.ts` serving `applications/<slug>/` over the tailnet, so the review card's new
`📂 Open the full folder` line reaches `claims-used.md`, `strategy.md` and the HTML sources
that an attachment cannot carry - and reaches any application months later, once the chat
has scrolled. Runs unprivileged with no secrets in its environment and a read-only
filesystem; `tailscale serve` fronts it. 22 TypeScript tests pass (was 18). Deploy is three
commands in `apply-viewer.service`'s header plus `APPLY_VIEWER_BASE_URL` in the box's
`daemon.env`; until that variable is set the bot emits no link, so the halves can land in
either order.

~~**No review card has ever been sent.**~~ **Superseded 2026-08-08 15:53** - BMW is
`pending_review` with `reviewNotifiedAt` and an `artifactHash` set, so `announcePending()`
has now fired once. The rest of this paragraph still describes the other three records,
which predate the bot. The gate is live and has had nothing to show. The only Telegram
traffic the loop has produced about an application is the give-up notice from
`select.ts:91`. So the PDF-attachment path, and now the folder link, are correct in code
and **unexercised in production**.

**The fix is confirmed end to end on the box, 2026-08-08 13:38.** BMW was reset to a clean
scaffold (both documents restored from `_template`, `draftAttempts` 0) and re-run by hand:

```
13:50  Lebenslauf  14,016 -> 14,729 bytes   DRAFTED   (~12 min, first CV this loop has made for BMW)
13:52  Anschreiben  5,526 ->  7,986 bytes   DRAFTED
13:52  claims stage, still running at 14:10 (18+ min)
```

`draft_cv` had never executed once since the drift; it ran and wrote a real document. That
settles the fix. **The run had not finished when this was written - `verify.ts` had not yet
graded it and no review card had been sent.** Check the outcome before assuming success:

```
ssh alpiclawd 'systemctl is-active apply-draft.service; tail -20 "$(ls -t /srv/advocate-data/apply/state/draft-logs/* | head -1)"'
```

**Final outcome of that run: `claims` failed, everything above it passed.**

```
analyse:      skipped        draft_cv: ok 723.2s, 1 turn      draft_letter: ok 127.7s, 1 turn
claims:       FAILED 2407.7s, 0 turns, 0 tool calls - every tier, key 1/7 only
```

**The rotation question is now settled, and the answer is that rotation was never the
fix.** The probe was re-run minutes after this failure, against the same model that had
just failed on key 1: **7/7 keys OK**. Same key, same model, same window - a short request
succeeds while the real `claims` request returns `finish_reason='error'`. So the failure is
**request-shape dependent**, not per-key and not upstream capacity, and exhausting all
seven keys would have failed seven times instead of one.

~~`claims` preloads 65,987 chars and asks for a long generation, so the model burns its
budget thinking and never emits the tool call.~~ **Superseded 2026-08-08 - this paragraph
was wrong and is kept only so the wrong idea is not re-derived.** Nothing was burning a
reasoning budget, and the preload was never the problem; see the top of this file. Vodafone
parking at 3 with both documents drafted is still probably the same defect, and it should
re-run once `claims` is proven.

`render` needs no model at all (1.4s, deterministic), so `claims` is the only real blocker
between a drafted application and a review card.

**Next session starts here: re-run BMW by hand and get the first review card.** The fix is
deployed on the box (`/srv/advocate` at `065b018`) and the contaminated artifacts are
cleared.

```
ssh alpiclawd
systemctl start --no-block apply-draft.service   # ~6 min, watch: journalctl -fu apply-draft
```

Both open decisions were settled by Alp on 2026-08-08 and are already applied: the letter
drafted against the template CV was discarded, and `draftAttempts` was reset to 0.

**Restore a document to scaffold state by copying `_template`'s copy in, never by deleting
it.** `write_document` splices a body into the existing shell, so an absent file fails the
stage for a reason that has nothing to do with drafting.

Backup of everything removed: `alpiclawd:/root/advocate-cleanup-2026-08-08/`.

Then: component 4 (the submitter).

Phase C (tailored CV/cover-letter drafting) is underway; first validation run complete.
CSS → design system and HTML → Jinja templates remain queued behind it, per the
2026-08-02 phase reorder below.

## The objective, restated by Alp 2026-07-31 — read this before writing any document

The goal is **the role that best advances Alp's AI/ML career, at a prestigious company
where possible**. The dossier, the claim store and the grounding check are *instruments*
for that, not the deliverable — a defensible document nobody reads is a failure. His
words: *"we dont want to lie, but everybody MUST exaggerate their skills."*

**He is admitted to the TUM Wirtschaftsinformatik MSc**, which is why he is moving to
Munich (assumed start: winter semester, October 2026 — unconfirmed). So the profile is:
- **Preferred** — Werkstudent, part-time, or genuinely flexible roles compatible with the MSc.
- **Also in scope** — full-time, if strong enough that taking it and dropping the MSc wins.
- **Munich is a plus, not a filter.** He will live there; remote and flexible also qualify.
- **Rank on prestige and career trajectory**, not only on requirement match.

The six-weeks-of-LLM-work problem (§8.1) is a weak hand for a senior posting and a very
strong one in a Werkstudent pool — that portfolio on top of ~3.5 years professional
engineering enters top-decile there. Werkstudent at a prestigious Munich AI company is
the efficient door, and it is the ranking bias the fit-scorer should carry.

Split the two axes and treat them oppositely:
- **Checkable facts** — dates, employers, degrees, tech actually used, metrics. Never
  inflate. This is what `gap` grades and forbidden phrasings are for, and the reason is
  tactical: Azure dies in the first technical screen, "7–13 months of LLM work" dies
  against the commit dates the CV invites a reader to check.
- **Framing, ordering, emphasis** — push hard. The strongest true framing usually beats
  the vague inflated one anyway: "a production autonomous agent, a from-scratch RAG stack
  with a measured RAGAS baseline, an MCP server and a voice agent, in six weeks" outsells
  "1 year of LLM experience" *and* survives scrutiny. Six weeks is the flex, not the caveat.

Do not volunteer caveats nobody asked for, and do not read a `⚠️` in the dossier as
licence to soften a claim that is true.

**Settled 2026-08-02 — discovery moves to the front.** The concept doc scheduled it as
Phase 3, behind document generation and eval. That was backwards for the stated goal, and
redundant: discovery already exists and works. It is the TypeScript hunter in
`advocate-data/job-search/`, deployed on `alpiclawd` under a 3-hourly systemd timer.

**It is not being ported to Python.** Porting a working scraper buys nothing and costs the
hiring window. Later, the hunter writes leads into the same Postgres and Advocate reads
from there. Revised order: discovery (now) → documents by hand → `apply` subgraph →
eval → the rest of the concept doc's phases.

**The window is the constraint.** Winter-semester Werkstudent hiring runs August–September;
the first applications should go out within 4–6 weeks of 2026-08-02. That decides every
build-vs-do tradeoff. Documents for the first batch are drafted **by hand**, in the loop,
against the dossier and `claims.yaml` — those hand-drafts become the spec for the `apply`
subgraph and its eval fixtures, instead of the concept doc's guess.

**Dossier debt** in `advocate-data/EVIDENCE_DOSSIER.md`:
- §1 lists Würzburg and sells the ~15–20 km Giebelstadt commute as an advantage. Dead.
- §2 says "never imply a Master's". **Done 2026-08-05** — annotated superseded, and TUM
  MSc active enrollment is now a real claim (`edu.tum_msc.active_enrollment`), not just a
  noted opportunity. See Phase C below.
- §8.1's seniority framing was written for full-time postings and does not apply to a
  Werkstudent application, where six weeks of LLM work is a strength rather than a ceiling.

## In flight

- Branch `add-context-pack` (this repo) — restructured into `src/advocate/`, concept doc,
  Postgres store, claim schema. All committed; 5 commits ahead of `main`, not pushed.
- Branch `rescope-hunt-v2` (`advocate-data`) — the hunt re-aimed at the TUM/Werkstudent
  profile. **Awaiting review before merge to master**, because the box pulls
  `master --ff-only` every tick and would deploy it immediately.

## The hunt, re-aimed 2026-08-02

The scorer was still ranking against the pre-reset profile. Now:
- Five-axis scorecard — `ambition`, `prestige`, `reachability` as a weighted **geometric**
  mean, plus `mscCompatible` / `munichViable` as hard gates on the Werkstudent track.
  Geometric because the axes are conjunctive: arithmetically a Staff ML Scientist post at a
  top lab scores 67 and tops the shortlist all week without ever replying.
- Full-time roles face a higher floor (72) than Werkstudent ones (50). The MSc is the
  default path, so a merely-decent full-time job is a *worse* outcome than MSc + Werkstudent
  and must not compete as an equal.
- Curated 4-tier employer table, because a small model ranks brands differently every run
  and an unstable ranking key makes the shortlist unreproducible.
- Databank reset: 432 scorable postings archived with all derived fields stripped;
  `seen_jobs.json` cleared.

**Two real bugs found by reproducing rather than reasoning:**
1. The "28 of 80 judgment failures" recorded on 2026-07-28 were **not** a gate limit. The
   default model reasons in the open and spent its entire 400-token ceiling thinking,
   truncating before it emitted a single axis. Parse rate 0/8 before the fix, 6/6 after.
   A truncated reply is now rejected even when it parses — it produced a complete,
   plausible, wholly fabricated scorecard built from the model's scratchpad.
2. `markSeen()` marked every fetched posting whether or not it was judged, so on the free
   tier (50 req/day/account) most of a run would be burned permanently — fetched once,
   never judged, never seen again, with no error. Unjudged postings are now deferred.

**Indeed removed as a source.** HTTP 403 on all six queries and every detail fetch, every
tick since 2026-07-29. The link-scan fallback scraped titles off the 403 pages, so it
failed quietly: 323 rows with a real title, no company, no description — 43% of the
databank. Archived separately rather than deleted; the titles are real.

## Open questions — carried, not blocking

1. **Claim-store source of truth.** YAML in `advocate-data` (git diff review, offsite
   backup, DB rebuildable) vs. the concept doc's DB-authoritative model. Recommendation
   is YAML-in-git; the load is a `truncate` + reinsert, so the projection is cheap.
2. **German renderings.** A claim with no `de` phrasing has no approved German wording.
   May the drafter translate from `en`, or is that the generator writing facts? Numbers
   and proper nouns are where this bites. Undecided — affects every German application.
3. **Composite verification.** `character.fast_learning` draws on three claims with three
   different verifications; its own value is currently a judgement call.
4. **Withdrawn claims** are not constrained to have empty surfaces, so retrieval *must*
   filter `status = 'active'`. Enforced by convention today, not by the schema.
5. Several sample rows have **inferred surfaces** (flagged in their `note`) — the dossier
   does not state which document they belong in. Needs Alp.

## Next up

1. **Checkpoint 1** — Alp reviews the rubric, the tier table and `TARGET_COMPANIES`, then
   `rescope-hunt-v2` merges to master and the box deploys it on the next tick.
2. **Phase B** — first live run is **done** (2026-08-02, see below); still to write is
   `advocate-data/docs/shortlist-2026-08.md`: top ~25 ranked with per-axis breakdown,
   arrangement and an honest reachability read. Alp cuts it to 5–8. No longer gated on
   the OpenRouter quota — that constraint is gone.
3. **Phase C is underway, run by hand as the `cv-drafter` Claude Code skill** in
   `advocate-data/.claude/skills/cv-drafter/` (built 2026-08-05). First validation run
   (Temedica, composite 76) is complete and ready to send. The apply/send loop around it
   is being built in `advocate-data/apply/`: state store, approval bot and headless draft
   loop are done (Buckets 1-3, 2026-08-06), send channels and an end-to-end dry run are
   not. None of it is deployed yet. Detail lives in `advocate-data/docs/context/
   apply-send-loop.md` and `cv-drafter-skill.md` — read those before resuming this
   workstream, not this file alone.

   **Harness decided 2026-08-06** (this was the open block): the box cannot authenticate
   Claude Code, so the draft loop moves to **OpenCode on `alpiclawd`** (installed, 1.18.14),
   with the drafting model reached OpenRouter-first across the seven keys
   (`nemotron-3-ultra-550b`), then OpenCode Zen, then NVIDIA NIM. **OmniRoute was measured
   and rejected for the drafter** — it cannot pin a model and its free pool is empty for
   most of the day; it stays unchanged for the hunt's fit gate. Not built yet: `agent.ts`
   still shells out to `claude -p`. See `apply-send-loop.md` 2026-08-06.

   **The box can render PDFs as of 2026-08-06.** Google Chrome stable 151 installed and
   `/srv/advocate` cloned, so `build_pdf.py` is present and works there — verified, 3-page
   PDF in 0.6s. Two things this repo owns came out of it: `build_pdf.py` was Windows-only
   (`CHROME_CANDIDATES` held three `C:\Program Files\…` paths), so it now resolves the
   browser off PATH with an `ADVOCATE_CHROME_BIN` override; and **`/srv/advocate` tracks
   this `add-context-pack` branch, not `main`**, because the `src/` restructure that
   introduced `build_pdf.py` is still unmerged. Merging this branch means repointing that
   checkout, or the box keeps drafting against a dead branch.

   **The harness is done as of 2026-08-06.** Both gates cleared — nemotron-3-ultra
   drives OpenCode's file-tool loop correctly, and the 45-minute latency that looked
   fatal was **OpenCode Zen's free-tier queue, not the model**: the same probe against
   `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` finished in **53 seconds**. So
   `agent.ts` no longer shells out to `claude -p`; it drives OpenCode across a
   failover chain (OpenRouter → Zen → NIM) with the seven keys rotating inside tier 1
   on 429, cv-drafter's SKILL.md inlined into a brief because OpenCode does not
   discover `.claude/skills/`, and the permission lists ported across.

   **The drafting subgraph now produces a real application. 2026-08-07.** The
   single-conversation version stalled twice, so the agent node was split into
   `analyse -> draft_cv -> draft_letter -> claims -> render`: four short
   conversations plus a deterministic render, each stage ending on a filesystem
   check rather than the model declaring itself done, and each skipped outright if
   its output is already correct (so a retry resumes). Measured against the live
   Vodafone lead: the CV drafted in 2 turns, the cover letter in 3, both PDFs
   rendered, and **`verify.ts` passes on both documents** - the first complete
   drafted documents this loop has produced. The German is specific and grounded
   (SAP Innovation Award, TwInTraSys, the DVRP thesis, the TUM enrolment claim).
   `claims-used.md` is the one stage still not landing on the free route; detail
   and the three provider defects found underneath it are in
   `advocate-data/docs/context/apply-send-loop.md` and this repo's `decisions.md`.

   **Fixed 2026-08-07: Alp is in München, and the old address is now un-sendable.**
   Documents give the city only - no street address, no commute argument. The dossier
   said Würzburg and sold a Giebelstadt commute; both are gone. `verify.ts` enforces it
   by matching three *shapes* that assert residence (dateline, letterhead line, commute
   construction) rather than the word, because Universität Würzburg, Flexus AG and the
   Würzburger Wetterdaten project are all true and must survive. It fired correctly on
   the box's first real run. All four existing applications, including the three already
   sent, carry `97074 Würzburg`.

   **The end-to-end draft was run twice on 2026-08-06 and did not complete.**
   Everything below the model call is now verified on real data — selection, fetch,
   scaffolding, the inlined brief, the store, and `verify.ts` catching all eight
   defects so nothing false reached the approval gate. Both runs died inside the
   first model call on NVIDIA-side capacity errors (502 `ResourceExhausted`, then 504
   idle timeout) with zero tool calls. **The blocking defect: `opencode run` exits 0
   on a provider stream error, so `runDrafter()` declares success before checking,
   and the whole failover chain — key rotation, Zen, NIM — never fires.** Fix that
   before re-running, or attempts just repeat one broken tier. Two deploy steps also
   remain — the seven keys are not in the box's drafter environment, and Bucket 2
   needs BotFather. Detail in `advocate-data/docs/context/apply-send-loop.md`.
4. Then: `apply` subgraph specced from those drafts, eval at n≈7, CSS → design system and
   HTML → Jinja (driven by Phase C's needs), scaffolding (`pyproject`/uv, CI), and the
   remaining ~330 lines of `EVIDENCE_DOSSIER.md` migrated into claims.

## The hunt's LLM gate moved off OpenRouter, 2026-08-02

Alp's call: OpenRouter's free tier meters **50 requests per day per account** and the
primary account is shared with `nemotron-mcp`, so the fit gate could only ever judge a
quarter of a run (~52 of 203). Keyword score, not fit, was deciding the shortlist.

The hunt now calls a local **OmniRoute** gateway — OpenAI-compatible, pools other
providers' free endpoints behind `auto/*` combo routes, no API key. Measured 170 requests
with zero 429s and a 100% scorecard parse rate before deploying. Installed on `alpiclawd`
as a resident `omniroute.service`; the hunt's oneshot unit `Wants` it, so a dead gateway
degrades the run to keyword order instead of cancelling it.

First live box run the same day: **150 judgments, 0 failures, 119 dropped by the gates,
31 qualifying.** The top of the shortlist is now Werkstudent AI/DS at BMW, Allianz,
Rohde & Schwarz, BCG and Airbus — the profile this was re-aimed at. `LLM_MAX_CALLS` 40 →
150, `LLM_CONCURRENCY` 2 → 6, `TimeoutStartSec` 600 → 1800; wall clock, not quota, is now
the binding constraint. OpenRouter stays as `LLM_PROVIDER=openrouter` but is never a
silent fallback. Detail in `advocate-data/docs/context/job-search-agent.md`.

Open, found in the same journal and **not** fixed: 207 of 426 LinkedIn *detail* fetches
429'd, so about half the postings were judged on title + company alone. That is
`DETAIL_CONCURRENCY`, unrelated to the provider switch.

## Recently landed

- **Claim schema** — `src/advocate/knowledge/claims.py` + `migrations/001_claims.sql`,
  applied. Two deliberate departures from the concept doc, both forced by reading the real
  dossier: language-specific wording lives in a `phrasings` table (required / preferred /
  forbidden, with global forbidden rules carrying no `claim_id`) rather than `text_de` /
  `text_en` on the claim; and `verification` is separate from `grade`. `never_claim` bool
  collapsed into a `gap` grade. 14 stress-case claims loaded from
  `advocate-data/claims/claims.yaml`; five bad-row inserts verified rejected by CHECK
  constraints, not just by Pydantic.
- **Postgres 16.14 + pgvector 0.6.0 on `alpiclawd`** — role/db `advocate`, tailnet-only
  access (`pg_hba` + ufw on `tailscale0`), nightly `pg_dump` timer with 14-day retention.
  Verified end-to-end from the Windows laptop including a pgvector round-trip.
  Rationale and hardening notes in `decisions.md`.
- Restructure `job-agent` → `advocate`: `src/` layout, concept doc, data boundary enforced
  by `.gitignore` (personal data lives in the private `advocate-data` repo).
- Evidence dossier rebuilt by interrogation and scoped to the AI/ML target (in
  `advocate-data`, commit `bde9899`).
