---
topic: three-loop-architecture
updated: 2026-08-07
status: accepted 2026-08-07 - see §Settled
---

# Advocate as one system: hunt, draft, submit

Whole-system design record. Supersedes the component sketch in
`advocate-system-concept.md` where they disagree; that doc keeps the knowledge-base
design and the eval plan, which are unchanged.

## What this is for

**Land the role that best advances Alp's AI/ML career, inside the winter-semester
Werkstudent hiring window, without a false claim ever going out under his name.**

Two things stay true whatever the stack becomes: the system argues from evidence it
holds, and nothing irreversible happens without Alp seeing the exact thing that will
leave the system.

## Invariants

1. **Nothing leaves the system under Alp's name without Alp approving the exact bytes
   that go out.** Enforced by: `assertSendable` plus an artifact hash bound at approval
   (F1 below).
2. **No factual sentence in a document exists without a claim it traces to.** Enforced
   by: the claim store, the drafting stages' preloaded corpus, `claims-used.md`.
3. **No stage reports success on its own say-so.** Success is an observable property of
   the stage's output, checked by code that did not produce it. Enforced by:
   `stage.problems()` inside the subgraph, `verify.ts` outside it.
4. **A retry can never produce a second application to the same posting.** Enforced by:
   `idempotencyKey` checked inside the send transaction (F5 below).
5. **Personal data and secrets never enter `advocate`.** Enforced by: the repo split and
   `.gitignore`. Extended by F7: secrets do not enter `advocate-data` either.
6. **Marking work as handled happens on completion, never on attempt.** Enforced by:
   `draftAttempts`, the `drafted` resume path, the hunt's deferred-unjudged fix.

Invariants 3 and 6 are the same lesson learned five separate times (OpenCode exiting 0,
`finish_reason: "error"` inside a 200, `build_pdf.py` printing "image not found" and
exiting 0, `markSeen()` on unjudged postings, Indeed's 403 link-scan yielding 323
title-only rows). They are written here as laws so the third loop inherits them instead
of rediscovering them.

## Components

Three loops, one store, one knowledge base. The loops never call each other.

| # | Component | Owns | Autonomy | Where it lives |
|---|---|---|---|---|
| 1 | **Hunt** | Fetch, dedup, score, shortlist | Autonomous, 3h timer | `advocate-data/job-search/` (TS) |
| ~~1b~~ | ~~**Channel resolver**~~ | Dropped 2026-08-07 - the gate's "Listing gone" button covers it (F2) | - | not built |
| 2 | **Drafter** | Analyse, draft CV + letter, map claims, render PDFs | Autonomous behind the gate | `advocate/src/advocate/apply/` (Py), driven by `advocate-data/apply/draft.ts` |
| 2b | **Verifier** | Mechanical check of the artifacts | Autonomous | `advocate-data/apply/verify.ts` |
| 3 | **Gate** | Show the rendered PDFs, take approve / revise, capture the reason | Human | `advocate-data/apply/bot.ts` |
| 4 | **Submitter** | Fill the portal or send the email, upload, confirm | Human-triggered only | **new** |
| 5 | **Notifier** | Tell Alp what happened | Autonomous | `bot.ts` |
| S | **Store** | Every record's state, and the one place the loops meet | n/a | `applications.json` today, Postgres proposed (F5) |
| K | **Knowledge base** | Dossier, `claims.yaml`, phrasings, templates | n/a | `advocate-data` + `migrations/001_claims.sql` |

The drafter and the submitter are deliberately different components even though the
user's framing groups them: one produces a reversible artifact, the other takes an
irreversible outward action. That difference is the whole autonomy design.

## Seams

**The store is the interface. There is no IPC between loops.** Each loop reads records
in a state it owns the transition out of, and writes the next state. A loop that is down
when work arrives picks it up when it comes back, and no loop needs to know another
exists. This is already the pattern between the drafter and the bot; it is extended to
the submitter and, in F6, across the repo boundary.

| From → To | Carrier | Contract | On failure |
|---|---|---|---|
| Hunt → Store | `leads.jsonl`, git-committed | scored lead + `composite` | Stale leads; drafter picks nothing new |
| Store → Drafter | record at `drafted` | slug, posting URL, `draftTier` | Attempt counted, record stays `drafted`, retried up to 3x |
| Drafter → Verifier | filesystem, `applications/<slug>/` | 2 HTML + 2 PDF + `claims-used.md` + `strategy.md` | Record stays `drafted` with the reason in notes |
| Verifier → Gate | record at `pending_review` | + `artifactHash` | Bot announces on its next pass; `reviewNotifiedAt` set only after Telegram confirms |
| Gate → Drafter | record back to `drafted`, `draftTier` incremented, `revisionReason` set | the reason, verbatim | Nothing sends; the queue just does not advance |
| Gate → Submitter | record at `approved` + `approvedArtifactHash` | frozen bytes | `assertSendable` throws |
| Submitter → Notifier | record at `sent` or `send_failed` + `confirmation` | ref, company, evidence | Alp is told, with the failure reason |

**Dependency direction.** `advocate` (public engine, policy, schema, renderer) must not
depend on `advocate-data` (private data). Today it is inverted: `advocate-data/apply/`
holds the entire control plane and spawns `py -m advocate.apply.cli`. See F6.

## State machine

```
drafted ──verify ok──> pending_review ──approve──> approved ──claim──> sending
   ^                        │                                             │
   └───── revise (tier+1) ──┘                                    ┌────────┴────────┐
                            │                                    v                 v
                            └──reject──> rejected              sent          send_failed
                                                                                   │
                                                            (re-approvable) <───────┘
```

`withdrawn` is terminal from anywhere. Only `sending → sent` is irreversible in the
outside world, which is why it is the only transition that needs a real transaction.

## Findings

Ordered by what breaks first if ignored.

### F1. Approval is not bound to the artifact. This breaks invariant 1.

`assertSendable()` checks `status === "approved"` and nothing else. Alp approves PDF v1;
a retry or a hand-edit produces v2; the record is still `approved`; the submitter sends
v2. Nothing in the system notices.

**Fix:** hash the rendered PDFs when the record enters `pending_review`
(`artifactHash`), copy it to `approvedArtifactHash` on approval, and have the submitter
refuse on mismatch. Roughly fifteen lines. It is cheap now and unfixable-in-practice once
the submitter is live, because the failure is silent and looks like a successful send.

### F2. The apply channel is discovered too late. ~~Fix at selection~~ - answered by a button, 2026-08-07.

`leads.jsonl` stores the LinkedIn or StepStone **listing** URL (32 of 34 leads are
`de.linkedin.com`), not the ATS behind the Apply button. Personio, SuccessFactors,
Workday, Greenhouse and plain email are all live possibilities per posting.

Today that only becomes knowable at send time, which means a posting with no reachable
channel can consume a full drafting run and a slot in Alp's review queue before anyone
finds out. Both of those are the scarce resources.

**Proposed fix, not taken:** a `resolve_channel` step at *selection* time (component 1b).
Follow the listing, classify the apply surface, write `channel` and `applyUrl` onto the
record, and defer loudly on `unknown`.

**Settled 2026-08-07: not built. A button in the gate does the job instead.** Alp's call:
a dead listing is not worth a component. The review card already carries the posting URL;
when he taps it and gets nothing, a **🚫 Listing gone** button drops the record to
`withdrawn` and takes no action. Built the same day, alongside `/gone <slug>`.

The tradeoff being accepted is real and worth naming: a vanished posting still consumes a
full drafting run and a slot in the review queue, which is exactly what F2 argued against.
What changed is the price of clearing it - one tap, at a moment Alp is already reading the
card - against a resolver that has to classify Personio, SuccessFactors, Workday,
Greenhouse and plain email correctly, and be maintained as each of them changes.

**The trigger to revisit is now measurable rather than a guess.** Every drop writes
`Listing gone <stamp>` into the record's notes, so the rate is greppable. If dead listings
turn out to be common, that is the evidence for resolving the channel at selection after
all. The submitter still needs the classification - it just does it at send time, for
postings already known to be live, which is strictly fewer of them.

### F3. Rejection carries no reason, so escalation regenerates the same document.

`decide()` writes `Rejected by Alp via button` and nothing else. Handing that to Opus 5
buys a more expensive version of the same mistake.

**Fix:** the revise button sends a `force_reply` prompt; Alp's one-line answer lands in
`revisionReason`; the drafting stages get it verbatim; the stage outputs it implicates
are cleared so resume actually redoes them rather than skipping them as already-correct.
This is the highest value-per-line change in the whole plan, and it is a precondition for
the escalation tier being worth paying for.

Also split `reject` (dead, terminal) from `revise` (try again, tier up). They are
different intents and the current single button conflates them.

### F4. Escalation is a routing tier, not a fourth agent.

The ask is "on revise, the writer wakes up with Opus 5 high effort". Structurally that is
the same subgraph with `draftTier` on the record: tier 0 is the free OpenRouter/Nemotron
chain that `providers.py` already walks, tier 1 prepends Anthropic. Nothing else changes:
same stages, same tools, same confinement, same `verify.ts`.

Three concrete points:

- **Model id `claude-opus-5`.** Thinking is on by default; do **not** send
  `budget_tokens`, `temperature`, `top_p` or `top_k` - all four return 400. Depth is
  `output_config: {effort: "high"}` (or `xhigh`). `thinking: {type: "disabled"}` is
  rejected above `high` effort, so do not carry a disabled-thinking setting across.
- **Cache the corpus.** The ~85 KB preloaded system prefix (SKILL.md + dossier +
  `claims.yaml`) is byte-identical across all four stages and across every record.
  `llm.py` already sets `cache_control` on a stable prefix via `build_system_prefix()`;
  reuse it with `ttl: "1h"`. Cache reads cost ~0.1x, writes 1.25x-2x, and the minimum
  cacheable prefix on Opus 5 is 512 tokens, so this pays for itself inside one draft.
  Keep the volatile parts (posting, revision reason, per-stage instruction) strictly
  *after* the breakpoint or the cache never hits.
- **This is metered API billing, not the subscription.** Deliberate and fine, but it is a
  different cost model from everything else in the system and should be capped: tier 1
  only on explicit revise, never as an automatic fallback for a tier-0 provider error.
  A provider failure should retry tier 0, not silently escalate to a paid model.

### F5. There is no databank. There are four, and the submitter needs a real transaction.

`leads.jsonl`, `applications.json`, `applications/<slug>/`, `apply/state/*`, and a
Postgres instance holding claims that nothing else uses. That is workable today because
the drafter, bot and CLI collide rarely and `saveApplications()` is write-then-rename.

Atomic rename gives durability, not mutual exclusion. Two processes that read-modify-write
the same file lose an update and neither finds out. The submitter makes that matter: the
`approved → sending` claim is what stops a crash-and-retry sending twice, and it needs a
compare-and-swap, not a careful ordering of writes.

**Recommendation:** move the **state machine** to the Postgres already running on
`alpiclawd` (tailnet-only, nightly `pg_dump`, currently holding only claims). Artifacts
stay on the filesystem and in git, where the diff review and offsite backup are worth
having. This also gives Bucket 1's own deferred note its trigger: "Postgres migration
deferred to when this becomes the real submit subgraph" - that is now.

Also add a short monotonic **`ref`** at record creation. Alp asked for "application to
job offering with id 4"; today `id` is a content hash and `slug` is a 45-character
directory name. Neither is speakable. Every human-facing message uses `ref`.

### F6. The control plane has migrated into the private repo.

`advocate-data/apply/` now owns selection, scaffolding, verification, the store, the bot
and the timers, and it spawns `py -m advocate.apply.cli` for the drafting subgraph. So
the private data repo orchestrates the public engine repo. Consequences already visible:
the engine cannot be run or released alone on this path, deploy needs two checkouts on
two branches (`/srv/advocate` tracks `add-context-pack`, not `main`), and retry logic is
split across `draftAttempts` in TS and stage resume in Python.

**Not a port.** Rewriting working TypeScript buys nothing and costs the hiring window -
the same call already made correctly for the hunt. Two cheap fixes instead:

- **A boundary rule going forward:** new control flow goes in `advocate`. Specifically,
  component 4 is `advocate/src/advocate/submit/`, matching the concept doc's `submit`
  subgraph, not a fifth bucket in `advocate-data/apply/`.
- **Make the store the seam (F5).** Once state is in Postgres, the TS and Python halves
  are peers over a database instead of one shelling the other, and the direction problem
  dissolves without anyone porting anything.

### F7. Credentials in the application folder would be unrecoverable.

The ask is that the submitter save the portal email and password into the job offering's
folder. Two problems: `applications/` is git-committed and pushed to the box, so a
password written there is in history permanently - deleting the file does not remove it;
and it reverses the concept doc's settled portal policy ("the system never sees or stores
a password", `advocate-system-concept.md` §Portal auto-apply).

The underlying requirement is real and worth serving: Alp must be able to log back into
any portal he applied through.

**Alternative that meets it:** the submitter generates a random per-portal password,
never reused, and writes the credential to a `portal_accounts` table in the same
tailnet-only Postgres (encrypted at rest by the nightly dump policy already in place).
The application folder gets a pointer only - portal name, account email, credential id.
Telegram names the portal and the email, never the secret. Alp gets one place to look and
nothing lands in git.

If you want it in the folder anyway, say so and it goes in the folder - but
`applications/` would have to leave git first, and that costs the diff-review and offsite
backup the repo is currently providing.

### F8. Autonomy per component, stated once.

| Component | Tier | Why |
|---|---|---|
| Hunt | Autonomous | Idempotent; worst case is a bad ranking |
| Drafter | Autonomous behind the gate | Produces a proposal; costs tokens; reversible |
| Verifier | Autonomous | Fails closed |
| Gate | Human, always | The one place the irreversible action is authorised |
| Submitter | Human-triggered only | Irreversible, outward, under Alp's name |

No auto-send tier at any score. Already settled 2026-08-05 and restated here because the
third loop is where the temptation appears.

**The submitter's success condition is a confirmation artifact, not an HTTP 200**
(invariant 3): a screenshot of the submitted state, the confirmation page text, and the
confirmation email where one arrives. On an unexpected page, a CAPTCHA, or anything the
adapter does not recognise, it stops and hands the live browser over rather than guessing.
No CAPTCHA solving, no fingerprint spoofing, no rate-limit evasion - unchanged policy.

### F9. Queue depth is the gate's real failure mode.

The twice-daily cadence was chosen so the review queue never outpaces Alp's reading, and
that reasoning is right. Make it structural: the drafter skips its tick when
`pending_review` count is at or above a cap (3). A cadence is a guess about throughput; a
cap is the invariant the cadence was approximating.

## What is already built

The ask is largely a description of what exists. The genuinely new work is small.

| Asked for | State |
|---|---|
| Hunt fills the databank | Built, deployed, 3h timer |
| Drafter wakes, reads it, picks score > 65 | Built. `APPLY_DRAFT_MIN_COMPOSITE` defaults to **65**, on top of the hunt's per-track floors and hard gates |
| Nemotron writes CV + Anschreiben in German | Built. Five-stage LangGraph subgraph; verified end to end on the Vodafone lead |
| Check the documents are good | Built. Stage gates plus independent `verify.ts` |
| Set a "ready to review" flag | Built. `status: pending_review` |
| Telegram message with the PDFs and two buttons | Built. `bot.ts` sends `sendDocument` plus an inline keyboard |
| Revise → rerun on Opus 5 high effort | Built 2026-08-07. F3 + F4 |
| Listing is gone → take no action | Built 2026-08-07. F2 |
| Third loop applies on the platform | **New.** F8 |
| Save portal credentials | **New,** and see F7 |
| "Application to offering N has been made" | **New.** Needs `ref` (F5) |

## Built 2026-08-07: F1, F3, F4

The first bucket of the accepted order is done and tested. What is worth knowing
beyond "it works":

**F1 is two checks, not one, and the second is the load-bearing half.**
`assertSendable(record, currentHash)` takes the fingerprint as a *required* argument -
an optional one is one a caller forgets, and forgetting it here looks identical to the
guard working. `artifactHash()` (in `verify.ts`) hashes the rendered PDFs, filenames
included. The bot **re-reads it at approval** rather than trusting the value stored when
the card was sent: the window between "Alp was shown these documents" and "Alp tapped
approve" is exactly when a retry can change them. On a mismatch the record goes back to
`pending_review` with the new fingerprint, which drops the announcement marker and makes
the next pass send a fresh card, so the mismatch self-heals rather than needing a human.

**The three existing `approved`/`sent` records carry no fingerprint and are therefore
not sendable by the automated path.** That is the guard working, not a migration bug -
they were approved before documents were fingerprinted at all, so nothing records what
Alp said yes to. Sending them by hand is unaffected; `/resend` and re-approve is the
route back if Bucket 4 ever needs them.

**F3 splits reject from revise, and the reason is what makes a record selectable.**
Three buttons now. Revise moves the record to `drafted`, bumps `draftTier`, clears the
old reason, and asks why with a `force_reply`. The key rides in the prompt text, so the
answer is matched back to its record by reading it out of `reply_to_message` - no
pending-question file, nothing a restart can lose. `select.ts` skips any record at
`draftTier > 0` with no reason, so the absence of a reason *is* the "waiting on Alp"
state and there is no second flag; `/pending` lists those next to the review queue so
they are visible rather than merely stuck.

**F4's escalation is prepended to the chain, never appended.** A run that starts on
Anthropic can fall back to free; a run that starts free can never fall *up*. That is
what keeps a 502 from NVIDIA - a capacity failure with nothing to do with model quality -
from spending money. A missing `ANTHROPIC_API_KEY` degrades a revision to the free chain
with a loud log line rather than failing it.

Two things about the model configuration are deliberate and easy to undo by accident.
**No `temperature`, `top_p` or `top_k`** - Opus 5 returns 400 for all three. **No
`thinking` and no effort parameter** - on Opus 5 thinking is on by default and effort
defaults to `high`, so passing neither *is* the "Opus 5, high effort" that was asked
for. The only reason to add an effort argument later is to reach `xhigh`, and that is
worth verifying against the installed client rather than assuming.

**The corpus is a cache breakpoint on the paid rung only** (`_cacheable` in
`providers.py`). It is ~85 KB, byte-identical every turn and identical across every
application, and each turn re-sends it. The volatile half - the stage task, the revision
brief, the conversation - stays after the breakpoint, which is why the revision reason
went into the *task* message and not the system prompt. Default 5-minute TTL, no beta
headers: the win being captured is within a stage, where turns are seconds apart.

**Two traps found while building it, both of which would have shipped silently.**

1. **Resume-by-skipping would have no-opped every revision.** A stage is skipped when
   its `problems()` are empty, which is right after a crash and catastrophic after a
   revision: a draft that reached Alp has no mechanical problems *by definition*, so all
   four stages would skip, `render` would re-render the document he rejected, and the run
   would report a successful revision. A revision now re-runs every drafting stage.
2. **A revision stage could then "succeed" without writing anything.** With the checks
   already passing, a model that replies with prose and makes no tool call would end the
   stage instantly. On a revision a stage additionally has to have landed a successful
   write this run, and the pipeline judges the stage by the same rule its loop exited on
   rather than recomputing from `problems()` - the two disagree exactly here, and in the
   dangerous direction.

Both are the invariant-3 shape, caught by writing the test before believing the feature.
Tests: 16 in `advocate/tests/test_draft_pipeline.py` (`PYTHONPATH=src py tests/test_draft_pipeline.py`),
9 in `advocate-data/apply/src/selftest.ts` (`npm test`), which is the first coverage
`assertSendable` has ever had - it was written for a sender that does not exist, so its
first real run would otherwise have been the first time it mattered.

## Settled

Alp's calls, 2026-08-07, on the three questions this record was written to ask.

### Portal credentials live in Postgres, never in the application folder
The submitter generates a random per-portal password, never reused, and writes it to a
`portal_accounts` table in the tailnet-only Postgres on `alpiclawd`. The application
folder gets a pointer only: portal name, account email, credential id. Telegram names the
portal and the email, never the secret.
**Rejected: plaintext in `applications/<slug>/`,** which was the original ask. That
directory is git-committed and pushed to the box, so a password written there is in
history permanently and deleting the file does not remove it. Keeping it would have meant
taking `applications/` out of git, which costs the diff review and the offsite backup the
repo currently provides. **Also rejected: an age/gpg-encrypted file in the folder** - it
survives git safely but needs the key on every machine that reads it and creates a second
secret-management path alongside the Postgres one.
**Cost accepted:** reading a credential now needs the tailnet and a DB round trip, not
just the folder.

### The state machine moves to Postgres; artifacts stay on the filesystem and in git
`applications.json` keeps working until the submitter exists, then the record state moves
to Postgres. Artifacts (`applications/<slug>/`) do not move - the git diff review and
offsite backup are worth having, and documents are not what needs a transaction.
**Rejected: a lease field plus compare-and-swap on the JSON file.** It is enough for the
duplicate-send guard alone, but it leaves the four-store split and the F6 dependency
inversion in place, and Postgres is already running for the claim store.
**Rejected: deferring until after the submitter is written**, which would have made the
duplicate-send guard the last thing trusted rather than the first.
**Cost accepted:** the loop now needs the box reachable to run at all, where today it
degrades to laptop-local. Mitigated by the nightly `pg_dump`, not eliminated.

### A dead listing is a button, not a component
See F2. The review card carries the posting URL; when it opens nothing, **🚫 Listing gone**
drops the record to `withdrawn` and nothing is sent. **Rejected: component 1b**, a
`resolve_channel` step at selection time. It buys back a drafting run and a queue slot per
dead posting, at the cost of classifying five ATS vendors correctly and forever.
**Cost accepted:** a vanished posting is still drafted before anyone finds out. The drop
rate is greppable in the notes, and if it turns out to be high, 1b comes back with evidence.

### Build order: close the existing loop before adding an irreversible component
F1 (artifact hash binding), F3 (split reject/revise, capture the reason) and F4 (the
Opus 5 tier with prompt caching) come first, as one bucket. Then deploy, then component 4.
**Rejected: going straight to the submitter,** accepting F1 and F5 as gaps to close along
the way. Fastest to an end-to-end application and the highest risk of exactly the two
silent failures this record exists to prevent.

## Open questions

1. **Channel build order.** Email and portal in parallel was settled 2026-08-05. With F2
   answered by a button there is no resolver run to learn from, so this is now decided by
   the first few postings Alp actually reaches: build the adapter for whatever they use.
2. **Escalation ceiling.** How many revise rounds before a posting is dropped, and whether
   tier 1 ever gets a second attempt. Not blocking; defaulting to 2 rounds.
