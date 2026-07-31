# Decisions — job-agent

Budget: 700 tokens. One entry per settled decision. Newest first. The point of this file
is to stop an agent from cheerfully re-proposing something already rejected.

Prune aggressively: once a decision is so embedded it could never be revisited, delete it.

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
