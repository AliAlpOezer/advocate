# Status — advocate

Last updated: 2026-08-06

## Current focus

Phase C (tailored CV/cover-letter drafting, run by hand as `advocate-data`'s
`cv-drafter` skill) is underway; first validation run complete. CSS → design system
and HTML → Jinja templates remain queued behind it, per the 2026-08-02 phase reorder
below.

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
