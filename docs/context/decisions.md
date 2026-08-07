# Decisions — job-agent

Budget: 700 tokens. One entry per settled decision. Newest first. The point of this file
is to stop an agent from cheerfully re-proposing something already rejected.

Prune aggressively: once a decision is so embedded it could never be revisited, delete it.

### Secrets never enter `applications/`, and record state moves to Postgres
Date: 2026-08-07 · Status: settled · Full reasoning in `three-loop-architecture.md` §Settled
Two calls made together when the whole system was designed as one. **Portal account
credentials go to a `portal_accounts` table in the tailnet-only Postgres**; the application
folder gets a pointer (portal, account email, credential id) and nothing else. **Rejected:
plaintext in `applications/<slug>/`,** which is what was originally asked for - that
directory is git-committed and pushed to the box, so a password written there is in history
permanently and deleting the file does not remove it. Also rejected: an encrypted file in
the folder, which needs the key everywhere and duplicates the secret path.
**The record state machine moves to Postgres when the submitter is built**, artifacts stay
on the filesystem and in git. **Rejected: a lease field with CAS on `applications.json`** -
enough for the duplicate-send guard alone, but leaves the four-store split and the
data-repo-orchestrates-engine-repo inversion in place, and Postgres is already running.
Cost accepted: the loop needs the box reachable, where today it degrades to laptop-local.

### Chrome is the only PDF renderer. Do not add a library for Linux.
Date: 2026-08-06 · Status: settled
`build_pdf.py` now resolves the browser off `PATH` (with an `ADVOCATE_CHROME_BIN`
override), so it runs on the laptop and on `alpiclawd` alike: a real `Lebenslauf`
renders there in 0.6s. **Rejected: WeasyPrint / wkhtmltopdf / Playwright's PDF
export.** Each is a *second* renderer, and the templates are hand-tuned to Chrome's
paged media - so the PDF Alp approves and the PDF a recruiter opens could paginate
differently, which is exactly what the approval gate exists to prevent. Chrome also
embeds fonts; a pure-Python library trades that away to save one `.deb`.
Install Google's `.deb` - Ubuntu's `chromium-browser` (noble, `2:1snap1`) is a snap
stub, and snap is the wrong shape for a systemd unit with a minimal `PATH`.

### Claim wording lives in a `phrasings` table, not `text_de`/`text_en` on the claim
Date: 2026-07-31 · Status: settled · Supersedes the claim schema sketched in
`advocate-system-concept.md`
Reading the real `EVIDENCE_DOSSIER.md` showed the sketched schema
(`text_de`/`text_en` + `evidence_grade` + `never_claim` bool) could not express four
things that are pervasive in it, so all four are now first-class:
1. **Phrasing rules on assertable claims.** "Never write *Travelling Salesman Problem*",
   "never *identified the need for*", "say *familiar with*, not *read*". These constrain
   claims that are perfectly true, so a `never_claim` flag cannot carry them, and a
   free-text field invites the drafter to paraphrase around them. `phrasings` rows are
   `required` / `preferred` / `forbidden` per language; a row with **no `claim_id` is a
   global rule** scanned against every draft regardless of what was cited.
2. **`audience_scope`.** Dossier §8b is SSI Schäfer-only and says explicitly that none of
   it transfers. Nothing in the sketch stopped it leaking into an unrelated AI/ML letter.
3. **`requires_claims` + `min_supporting`.** §10.3 is assertable only when paired with ≥2
   of three named artifacts. That is citation cardinality, not a grade.
4. **`verification` split from `grade`.** Where evidence came from and how strong it is are
   independent: the "top 5 state high school" claim is self-reported yet usable;
   scikit-learn is well-documented coursework that must never read as experience.
Also: `evidence_grade`'s `never-claim` value and the redundant `never_claim` bool collapse
into a single `gap` grade, with "gap ⇒ no surfaces" as a CHECK constraint. Constraints are
enforced in Postgres as well as Pydantic, because the loader will not be the only writer.
Cost we accepted: a claim now spans two tables, so every read needs a join, and curating
one takes more thought than filling in two text fields.

### Self-hosted Postgres 16 + pgvector on the `alpiclawd` box, not Supabase
Date: 2026-07-31 · Status: settled · Supersedes the "Supabase" line in
`advocate-system-concept.md` (the store choice, not the Postgres choice)
Postgres 16.14 + pgvector 0.6.0 on the home Ubuntu server (`alpiclawd`, a converted
ThinkPad, x86_64, 4 cores / 7.6 GB), reachable only over Tailscale. Chosen over Supabase
(no third-party holds the evidence base; no free-tier pause) and over SQLite.
The concept doc's stated reason for rejecting SQLite — "a local SQLite checkpoint does
not give durability across restarts" — is **wrong**; `SqliteSaver` persists to disk fine.
The real reasons: (a) development happens on the Windows laptop while the DB lives on the
box, and SQLite has no network protocol; (b) the hunt runner, gate API and UI are
concurrent writers, which is where SQLite starts returning `database is locked`.
Hardening: `listen_addresses = '*'` deliberately, with access restricted by `pg_hba`
(`100.64.0.0/10` + `fd7a:115c:a1e0::/48`, scram-sha-256) and ufw (`5432 on tailscale0`).
Binding straight to the Tailscale IP would race `tailscaled` at boot and leave Postgres
dead after a reboot. Nightly `pg_dump -Fc` at 03:30 via `advocate-backup.timer`, 14 dailies
in `/var/backups/advocate`. Credentials: `/root/.advocate/` on the box, `.env` locally.
Cost we accepted: pgvector 0.6.0 is the distro build, so no `halfvec`/`sparsevec` (0.7.0+)
— irrelevant at this corpus size, and staying on distro packages keeps it inside
`unattended-upgrades`. Also: the box is a home machine on WiFi, so it is a real
single point of failure, and backups are on-box only.

### Prompt-for-JSON + Pydantic-validate instead of `with_structured_output`
Date: 2026-06-17 (repo init) · Status: settled
Chose manual JSON-object prompting + `SkillExtraction.model_validate()` (with up to 3
retries, then skip the posting) over LangChain's `with_structured_output`, because free
OpenRouter routes (`gpt-oss-120b:free`) were found to ignore the schema and return
reasoning-only/empty responses (learned in the earlier TS spike, per `extract.py`
docstring). This works uniformly on any provider — Claude produces clean JSON, free
routes are flaky so failures degrade to `[]` for that posting rather than aborting the run.
Cost we accepted: hand-rolled JSON extraction/regex parsing (`_parse_json_object`)
instead of relying on the library's structured-output guarantees.

### Roadmap coverage is hardcoded Python data, not RAG'd
Date: 2026-06-17 (repo init) · Status: settled
`roadmap.py`'s `ROADMAP_COVERAGE` dict is curated by hand from the AI-Engineer roadmap +
Munich market analysis, per its docstring: "legitimate domain knowledge, not something
to RAG over 17 notes for — keep it as code." RAG over postings themselves is a separate,
explicitly deferred roadmap item (README "Roadmap (next phases)").
Cost we accepted: coverage table needs manual updates as the personal roadmap changes;
it will silently go stale if not kept in sync.

### Hybrid LLM provider: free OpenRouter default, Anthropic opt-in
Date: 2026-06-17 (repo init) · Status: settled
Default provider is `openrouter` (`gpt-oss-120b:free`, $0) so the tool is free to run
routinely; `--provider anthropic` is available for reliable structured output plus real
prompt caching (`cache_control` on the stable extraction/synthesis system prefix).
Cost we accepted: default runs inherit free-route flakiness (handled via retry/fallback
above) instead of always getting Claude's reliability.

### Public-endpoints-only scraping, back off on rate-limit rather than evade
Date: 2026-06-17 (repo init) · Status: settled
`sources.py` docstring: "PUBLIC sources only. No login, no credentials, EVER... No proxy/UA
rotation, no CAPTCHA solving. On 429/999 we back off, never evade." LinkedIn access uses
the unauthenticated guest job-search endpoints, not the authenticated API.
Cost we accepted: LinkedIn coverage is capped by whatever the guest endpoint allows
before it starts rate-limiting; no workaround is attempted.

## Three provider defects, each of which looked like a model refusing to work

Found 2026-08-07 while getting the split to draft. All three are recorded because each
one cost a run and each would be re-introduced by an obvious-looking change.

**`finish_reason: "error"` arrives inside a 200 response.** Replaying the failing request:
2,464 completion tokens, all reasoning, no content, no tool call, HTTP 200. The chain
accepted it as an assistant turn, so a stage burned its whole budget on replies the
provider had already failed - and it read exactly like a model declining the job. This is
OpenCode-exits-0 one layer down. `ChainedChat.invoke` now classifies an unusable reply
(`finish_reason: "error"`, or no content and no tool call) as a provider failure.

**`tool_choice` forcing corrupts the argument. Do not re-add it as a stall fix.** One
probe, same model, same prompt, same session: unforced the model wrote `- alpha\n- beta`
with real newlines; forced it wrote `- alpha<br>- beta` with none, and the real file it
produced under forcing was 8,192 characters on a single line. Good content, unusable
shape. Re-run the probe in `graph.py`'s comment before believing otherwise.

**`ChatOpenAI(timeout=...)` is not a wall-clock bound.** A turn ran past 20 minutes against
a 600s client timeout; the run before it spent 53,893 seconds without completing a turn. A
read timeout is reset by anything arriving on the socket. The chain now enforces its own
deadline on a daemon thread, because the only other bound was the driver killing the
subprocess, which loses every stage at once.

Related: **`minimax/minimax-m3:free` no longer exists** (404, "unavailable for free"), and
OpenRouter has no free minimax variant at all. Tier 2 is `nemotron-3-super-120b-a12b:free`
- same family as tier 1, so a shared upstream can fail both. Accepted deliberately: the
fallback is there to survive a rate limit, not to be a second opinion on German prose.

## The drafting subgraph is five small stages, and no `finish` tool

Decided 2026-08-06, after the single-conversation version stalled twice. Asked for a
whole application in one conversation, nemotron-3-ultra read the posting and both
templates, wrote a correct `strategy.md`, and then stopped emitting tool calls - 3 turns
and 4 tool calls un-nudged, 6 turns and the *same* 4 tool calls with the nudge node live.
The loop was fine; the horizon was too long.

**The pipeline is now `analyse -> draft_cv -> draft_letter -> claims -> render`**, each a
fresh short conversation carrying the same preloaded grounding material and writing
exactly one file. `render` is not a model turn at all - it calls `build_pdf.render`
directly, which removes the two tool calls both stalled runs died before reaching.

**Rejected: switch to `minimax/minimax-m3:free`,** which was the standing alternative and
would probably have worked. Alp's call: he expects to buy OpenRouter credit and run
nemotron-3-ultra paid, so a design that only works on a different free model is the wrong
thing to build. minimax stays as tier 2 of the chain, which costs nothing.

**A stage ends when its output is right on disk, not when the model says so** - so there
is no `finish` tool any more, and `stage.problems()` is the exit condition. Three things
follow, and they are the reason this is a decision and not a refactor:
- a failure names a stage (`draft_letter never wrote the file`) instead of a turn count;
- a retry *resumes* - a stage whose problems are already empty is skipped without a model
  call, so `APPLY_DRAFT_MAX_ATTEMPTS` stops meaning "do the whole thing again";
- the nudge is computed from the folder, so a model that got it nearly right is told the
  leftover marker or the em dash, not asked to try harder.

The checks are deliberately the ones `verify.ts` would fail on later, moved forward to
where they are still cheap to fix. `verify.ts` is unchanged and still has the last word:
it is the independent cross-check, and duplicating a check in both places is the point,
not an accident.

**The model writes a `<body>`, not a document.** `write_document` splices it into the
house shell, so the print CSS that fixes the page count cannot be damaged by a draft and
the generated tokens roughly halve. Each stage is handed exactly one way to write, so the
CV stage has no tool that can touch the cover letter.

## The drafting agent is a LangGraph subgraph here, not an agent CLI shelled out to

Decided 2026-08-06, Alp's call, reversing the harness decision taken earlier the same
day. The drafting step of `advocate-data`'s apply loop ran by shelling out to an agent
CLI: first `claude -p`, then `opencode run` when the box could not authenticate Claude
Code. Both were the same bet - hand cv-drafter's SKILL.md to somebody else's agent loop.

**What called the bet.** Two live runs died inside the first model call, on a 502
(`Worker local total request limit reached (33/32)`) and a 504 (`Upstream idle timeout`),
after 206s and 310s, with zero tool calls. **OpenCode exited 0 both times**, so the
driver reported success for runs that wrote nothing, and the failover chain underneath
it - key rotation, Zen, NIM - was gated on a non-zero exit that this class of failure
never produces. Only `verify.ts` caught it, by noticing the documents were still
byte-identical to the SSI template.

**Rejected: patch the exit-code check and keep OpenCode.** It would have fixed that one
symptom while leaving the rest: a subprocess whose stdout only flushes at exit, key
rotation smuggled through `OPENCODE_CONFIG_CONTENT` because `OPENROUTER_API_KEY` is
ignored when `auth.json` exists, a permission dialect where `apply/**` fails open and
`**/apply/**` does not, version skew between the laptop's 1.14 and the box's 1.18, and a
session-title model that defaults to a paid one. That is a large accidental surface for
a job that needs four tools.

**Where it lives:** `src/advocate/apply/` - `state.py`, `tools.py`, `providers.py`,
`prompt.py`, `graph.py`, `cli.py`. The concept doc always specified an `apply` subgraph
here, so this is arriving at the planned destination rather than detouring; the OpenCode
harness was scaffolding that had to be thrown away either way. `advocate-data`'s
`draft.ts` keeps selection, scaffolding, `verify.ts` and the store - none of which ever
failed - and calls `py -m advocate.apply.cli`, so the swap stayed contained to
`agent.ts`, exactly as the previous swap did.

## Three design choices in the drafting subgraph that are not obvious

**Grounding material is preloaded, not fetched.** SKILL.md, `EVIDENCE_DOSSIER.md` and
`claims.yaml` (~85 KB, measured 85,587 chars) go into the system prompt verbatim. Under
OpenCode each was a read the model could silently skip, and a draft written without the
dossier looks identical to one written with it until every sentence is re-checked. The
free Nemotron route carries a 1M context, so there is no reason to make the one law
depend on the model choosing to read its own evidence. `references/cv-research.md` is
deliberately *not* preloaded - the skill says to read it only when a choice needs
justifying, and that instruction is still worth honouring.

**Confinement is a resolved-path check, not a pattern map.** Writes resolve under
`applications/<slug>/` or raise; `..`, absolute paths and symlink games are neutralised
by resolution rather than by string inspection. This replaces a glob dialect that was
measured to fail open and was never verified at all on the laptop's OpenCode version.
There is also no shell: rendering imports `build_pdf.render`, so the entire bash
permission surface - and any question of reaching `git commit` - does not exist.

**Rotation policy, refining rather than reversing "429 and nothing else".** That rule
was right about its target: a bad key or a wrong model id fails identically on all seven
keys, so rotating buries the reason. It had no case for what actually happened. Now:
rate limits rotate the key; transient upstream 5xx and timeouts retry once on the same
key then advance the tier, because both observed failures were NVIDIA-side capacity and
rotating keys against a saturated upstream just spends the pool to hit the same wall;
401/403/404 abandons the tier immediately without touching another key, which is Alp's
original rule preserved for the case it was written for.
