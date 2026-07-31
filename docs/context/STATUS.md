# Status — advocate

Last updated: 2026-07-31

## Current focus

Phase 0 (Extract) of the Advocate rebuild. The persistence layer is now provisioned;
next is turning `EVIDENCE_DOSSIER.md` into a machine-enforceable claim store.

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
