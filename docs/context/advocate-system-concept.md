---
topic: advocate-system-concept
updated: 2026-07-27
---

# Advocate - concept

Working name for the system `Resume_Project` becomes. "Advocate" because the
system argues Alp's case and, like an advocate, may only cite evidence it holds.
Rename freely; the name is not load-bearing.

## The design thesis

`EVIDENCE_DOSSIER.md` is already the most valuable artifact in this repo: a
hand-curated, evidence-graded claim base with explicit never-claim rules. Today
it is a document a human has to *remember* to obey. The entire system exists to
make it **machine-enforceable**.

That yields the one architectural constraint everything else follows from:

> **The generator never writes facts. It selects claim IDs and writes connective
> prose around them.** Every factual sentence in an output document traces to a
> claim ID carrying an evidence grade.

This is what separates the project from "an LLM writes a CV", and it is what
makes human review fast: the human reviews *claim selection*, not prose. It is
also the showcase - a verifiable-generation architecture, not a prompt chain.

## Decisions taken (2026-07-27, with Alp)

| Question | Chosen | Rejected |
|---|---|---|
| Scope | Discover → tailor → approve, full hunt loop | Tailoring-engine-only; full CRM |
| Knowledge base | Hybrid: structured claim store + vector precedent index | Claim store only; pure vector RAG |
| HITL gates | Two: strategy, then documents | One (final only); three (adds triage) |
| Outbound | Auto-apply to portals, scoped as below | Prepare-only; email-only |

## Stack

- **Python 3.12**, uv. **LangGraph** as the graph runtime - this is the showcase.
- **Postgres + pgvector** (Supabase). One store for claims, applications, runs
  and embeddings, *and* LangGraph's `PostgresSaver` checkpoints into it.
  Chosen over SQLite + Qdrant (Sage's stack) because HITL gates pause runs for
  days and must survive process restarts; a local SQLite checkpoint does not
  give that durably, and two stores buy nothing here.
- **Pydantic** for every structured output. **FastAPI** for the gate API and
  webhooks. **Next.js** for the approval UI (PDF preview needs a real surface;
  Telegram is the *notifier*, not the gate).
- **Playwright** (Python) for portal adapters. **Headless Chrome** stays the PDF
  renderer - `build_pdf.py` already works and does real CSS paged media.
- **pymupdf** for layout verification as a graph node, not a manual step.
- **LangSmith** tracing plus the Munich agent's own pattern: per-node timings and
  token/cost rows in a `runs` table.
- Tiered model routing as in the Munich agent: cheap model for extraction and
  normalization, strong model for strategy and drafting.

## The graph

Decomposed into subgraphs. "More complicated" should mean better decomposed, not
more nodes on one canvas.

### Top level: `hunt` (scheduled)

```
discover ──fan-out over sources──→ normalize_jd ──→ dedupe
                                                      │
                                              fit_score
                                              ╱        ╲
                                        reject          pass
                                          │               │
                                       archive      subgraph: apply
```

### Subgraph: `apply` (the interesting one)

```
company_research  ‖  jd_deep_parse
          ╲             ╱
        claim_retrieval          hybrid: structured filter + vector rerank
              ↓
        gap_analysis             requirement × claim coverage matrix
              ↓
          strategy               angle, claim set, gap handling, language
              ↓
    ◆ INTERRUPT - HITL Gate 1
              ↓
 draft_letter ‖ draft_cv ‖ draft_projectlist
              ↓
      grounding_check ──violation──→ revise (bounded loop)
              ↓
           render                  Jinja → HTML → Chrome → PDF
              ↓
       layout_check ──overflow──→ tighten → render (bounded loop)
              ↓
    ◆ INTERRUPT - HITL Gate 2
              ↓
      subgraph: submit → track
```

`layout_check` exists because pagination bugs are real and were hit by hand
today: a two-line spill onto a stray third page. Page-count conformance is an
assertion (letter = 1, CV = 2), not a human's job.

### Subgraph: `submit`

```
route by channel ─→ email | portal | manual
                       │
              portal_adapter (Playwright)
                       ↓
                  fill_form
                       ↓
              screenshot + diff
                       ↓
              submit (idempotency-guarded)
                       ↓
             verify_submission → record
```

## Knowledge base - the hybrid, in three layers

**Layer 1 - claim store (authoritative, structured).** Table `claims`:
`id` (stable slug, e.g. `flexus.cap.architecture`), `text_de`, `text_en`,
`kind`, `evidence_grade` (strong | moderate | coursework | never-claim),
`tags[]`, `metrics` jsonb, `period`, `source`, `verified_at`, `never_claim`
bool + reason.

Migrate `EVIDENCE_DOSSIER.md` into this table once; thereafter the dossier is
*generated from* the table. Source of truth inverts from document to database.

The never-claim rows matter as much as the positive ones: technologies the
candidate has only studied, tools never used in production, seniority bars not
met. `grounding_check` hard-fails any draft asserting one.

**Layer 2 - precedent index (pgvector).** Past application documents chunked by
paragraph with metadata (company, role, language, outcome). Consulted at draft
time for *style* precedent - "how was the SAP CAP experience phrased for a
consulting audience" - and never for facts. JDs embedded too, so fit-scoring can
compare against previously-scored roles.

**Layer 3 - research cache.** Company facts with provenance and TTL. The model
may not assert a company fact without a cached source row.

**The binding rule.** The drafting node receives the approved claim set as an
explicit ID list, style precedent chunks, and the JD requirement list. It emits
`(sentence, claim_ids[])` tuples - *structured output, not free prose* - which
are then assembled. Emitting structure rather than annotated text is what makes
grounding robust rather than a formatting convention the model can drift out of.
The stored mapping is exactly what Gate 2 renders.

## Evaluation - the part that makes it showcase-grade

Two hand-made applications already exist and become ground truth: SSI Schäfer
and BCG Platinion move into `eval/golden/`. Past work becomes test data.

- **Grounding precision** - share of factual sentences with a valid claim ID.
  Hard gate at 100%.
- **Never-claim violations** - must be 0, against an adversarial JD set written
  to bait Azure, Kubernetes and ABAP claims.
- **Requirement coverage** - share of JD requirements addressed, tracked per
  application.
- **Golden regeneration** - regenerate SSI and BCG, diff against what was
  actually sent, longitudinal scorecard in Sage's style.
- **LLM-as-judge** on tone and persuasiveness against a rubric.
- **Layout conformance** - page counts, no overflow.

## HITL, done durably

`interrupt()` plus the Postgres checkpointer, resumed with `Command(resume=...)`.
A run paused for days must hold no process. Telegram notifies with a deep link;
the web UI is the gate.

- **Gate 1 (strategy)** shows the requirement × claim coverage matrix, the
  proposed angle, gap handling and language choice. Human may veto claims, swap
  them, or rewrite the angle, then resume.
- **Gate 2 (documents)** shows PDF previews with claim-ID hover, a diff against
  any prior application to the same company, *and* the filled portal form.
  Approve / edit / reject-with-feedback; rejection feeds a bounded revision loop.

Gate 2 deliberately carries the submission authorization, which is how two gates
still cover an irreversible outward action. Nothing is ever submitted that was
not rendered and shown first.

## Portal auto-apply - built, with one scoping change

Alp chose auto-apply over prepare-only. Built as chosen, with the blast radius
bounded so it stays consistent with the data-ethics policy already shipped in
his Job-Market Analyzer (public sources only, no credential automation, no
anti-bot evasion):

- Playwright drives a **persistent browser profile Alp authenticated himself**.
  The system never sees or stores a password. This removes credential automation
  from the design entirely rather than mitigating it.
- **No CAPTCHA solving, no fingerprint spoofing, no rate-limit evasion.** When a
  portal presents a bot check, the graph does not try to pass it - it hits an
  explicit `human_takeover` node and hands the live browser over.
- Per-ATS adapters behind one `PortalAdapter` interface. This is the same
  pattern as `BusinessAdapter` in Voice Scheduler, which is worth stating in the
  README - it shows the abstraction instinct is habitual, not incidental.
- **Idempotency**: unique constraint on `(company, req_id)` in `submissions`,
  checked inside the submit node. Double-apply is made structurally impossible,
  not merely unlikely.
- Every submission screenshotted and archived.

First adapter should be **Phenom**, because BCG runs on it and the extractor
already exists (see memory `phenom-job-pages-embedded-json`).

## Repo shape

```
advocate/
  src/advocate/
    graph/      hunt.py  apply.py  submit.py  state.py  nodes/
    knowledge/  claims.py  precedent.py  research.py  grounding.py
    sources/    base.py  phenom.py  linkedin.py
    portals/    base.py  phenom.py
    render/     build_pdf.py  layout_check.py  templates/
    eval/       golden/  harness.py  scorecards/
    api/        gates, webhooks
    obs/        tracing, cost
  web/          Next.js approval UI
  migrations/
  docs/context/  docs/wiki/
```

The hand-written per-application HTML must become **Jinja templates**. The CSS
is already identical across the SSI and BCG documents - that shared CSS *is* the
design system, and extracting it is Phase 0 work.

## Phasing - checkpoint after each

0. **Extract.** CSS → design system; HTML → Jinja templates; dossier → claim
   schema + migration; SSI and BCG → golden fixtures.
1. **Core.** `apply` subgraph only. Manual JD input, both gates, render. No
   discovery, no submit. Proves grounded generation.
2. **Measure.** Eval harness against the golden set. **Do not proceed** until
   grounding precision is 100% and never-claim violations are 0.
3. **Discovery.** Sources, fit-scoring, dedupe, tracker.
4. **Precedent.** The pgvector style layer.
5. **Submit.** Email first, then the Phenom portal adapter.
6. **Operate.** Observability, cost dashboard, Docker, CI, scheduled runner.

## Risks

1. **The thesis depends on reliable claim citation.** If the model won't cite
   IDs consistently, the design degrades to "RAG with extra steps". Mitigated by
   emitting `(sentence, claim_ids)` structured output rather than annotated
   prose - the schema enforces what a convention would not.
2. **Long-paused runs.** Days-long HITL waits must hold no resources. Handled by
   interrupt + Postgres checkpointing; must be tested with a real restart, not
   assumed.
3. **Adapter rot.** ATS UIs change and Playwright selectors break. Treat adapters
   as best-effort: screenshot on failure, fall through to `human_takeover`.
4. **Over-tailoring.** Regenerating per role risks contradicting an earlier
   application to the same company or network. The precedent index plus an
   explicit consistency check against prior applications is the mitigation.
