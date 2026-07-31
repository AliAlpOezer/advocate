# Status — advocate

Last updated: 2026-07-31

## Current focus

Phase 0 (Extract) of the Advocate rebuild. Store provisioned, claim schema landed.
Next bucket is CSS → design system and HTML → Jinja templates.

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

**Open, and it affects the whole plan:** the concept doc schedules discovery as Phase 3,
behind document generation. Alp's stated goal is *finding* the job, which suggests that
ordering is backwards. Not yet decided.

**Dossier debt** in `advocate-data/EVIDENCE_DOSSIER.md`:
- §1 lists Würzburg and sells the ~15–20 km Giebelstadt commute as an advantage. Dead.
- §2 says "never imply a Master's". Superseded — **admitted to the TUM MSc
  Wirtschaftsinformatik** is now true, claimable, and one of the strongest lines available.
- §8.1's seniority framing was written for full-time postings and does not apply to a
  Werkstudent application, where six weeks of LLM work is a strength rather than a ceiling.

## In flight

- Branch `add-context-pack` — repo restructured into `src/advocate/`, concept doc landed,
  Postgres store provisioned, claim schema landed. Not yet committed.

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

1. Bucket 2: extract shared CSS from the SSI/BCG HTML into a design system; the three
   document types become Jinja templates.
2. Bucket 3: scaffolding — `pyproject`/uv, `ADVOCATE_DATA_DIR` resolution, package rename
   cleanup, CI. The repo currently has no installable package definition.
3. Migrate the remaining ~330 lines of `EVIDENCE_DOSSIER.md` into claims (14 of the
   hardest cases are done; the rest is volume, not design).

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
