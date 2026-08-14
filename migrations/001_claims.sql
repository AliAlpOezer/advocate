-- 001: the claim store.
--
-- Enum-like columns are `text` with CHECK constraints rather than native
-- Postgres enums: this vocabulary will grow as the dossier does, and adding a
-- value to a CHECK is a one-line migration where ALTER TYPE ... ADD VALUE is
-- not transactional and cannot be reverted.
--
-- Mirrors src/advocate/knowledge/claims.py. Where a rule can be enforced in
-- both places it is, because the loader is not the only thing that will ever
-- write here.

begin;

create table if not exists claims (
    id              text primary key,
    kind            text        not null,
    grade           text        not null,
    verification    text        not null,
    status          text        not null default 'active',

    statement       text        not null,
    surfaces        text[]      not null,
    tags            text[]      not null default '{}',
    metrics         jsonb       not null default '[]',

    audience_scope  text[]      not null default '{}',
    requires_claims text[]      not null default '{}',
    min_supporting  int,

    period_start    date,
    period_end      date,
    source          text,
    verified_at     date,

    supersedes      text[]      not null default '{}',
    note            text,

    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    constraint claims_kind_ck check (kind in (
        'personal', 'education', 'experience', 'project', 'skill',
        'achievement', 'certification', 'positioning', 'disposition')),
    constraint claims_grade_ck check (grade in (
        'strong', 'moderate', 'coursework', 'gap', 'ungraded')),
    constraint claims_verification_ck check (verification in (
        'source_verified', 'document_verified', 'self_reported')),
    constraint claims_status_ck check (status in ('active', 'withdrawn')),
    constraint claims_surfaces_ck check (
        surfaces <@ array['cv', 'cover_letter', 'project_list', 'interview', 'tone']),

    -- A gap-graded claim may never be asserted, so it can have no surface.
    -- This is the never-claim rule, expressed as a constraint rather than a flag.
    constraint claims_gap_has_no_surface_ck check (
        grade <> 'gap' or cardinality(surfaces) = 0),

    -- Ungraded material (dossier section 10) is not checkable and may only
    -- colour tone or answer a question that was asked.
    constraint claims_ungraded_surface_ck check (
        grade <> 'ungraded' or surfaces <@ array['tone', 'interview']),

    constraint claims_pairing_ck check (
        min_supporting is null
        or (cardinality(requires_claims) >= min_supporting and min_supporting > 0)),

    constraint claims_period_ck check (
        period_end is null or period_start is null or period_end >= period_start)
);

comment on column claims.statement is
    'What the claim is, for a human or model to read. Never copied into a '
    'document verbatim - approved wording lives in phrasings.';
comment on column claims.audience_scope is
    'Empty = universal. Non-empty restricts the claim to those employers; '
    'dossier section 8b (SSI Schaefer) must not transfer to another company.';
comment on column claims.metrics is
    'Array of {key, value, unit, approximate, note}. Values are kept as curated '
    'literals so the grounding check can assert every number in a drafted '
    'sentence appears verbatim in a cited claim.';

create index if not exists claims_tags_idx on claims using gin (tags);
create index if not exists claims_grade_idx on claims (grade) where status = 'active';
create index if not exists claims_kind_idx on claims (kind) where status = 'active';


-- Language-specific rules about how a claim may be written.
-- claim_id IS NULL means a global rule: wording that must never appear in any
-- document, whether or not the related claim was cited.
create table if not exists phrasings (
    id       bigserial primary key,
    claim_id text references claims (id) on delete cascade,
    lang     text not null,
    kind     text not null,
    text     text not null,
    reason   text,

    constraint phrasings_lang_ck check (lang in ('de', 'en')),
    constraint phrasings_kind_ck check (kind in ('required', 'preferred', 'forbidden')),
    -- Only a forbidden phrasing can stand alone; required/preferred wording is
    -- meaningless without the claim it renders.
    constraint phrasings_global_is_forbidden_ck check (
        claim_id is not null or kind = 'forbidden')
);

create index if not exists phrasings_claim_idx on phrasings (claim_id);
-- The grounding check scans every draft against all forbidden wording, not only
-- the wording of cited claims, so this is a hot path.
create index if not exists phrasings_forbidden_idx on phrasings (lang) where kind = 'forbidden';


create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists claims_updated_at on claims;
create trigger claims_updated_at before update on claims
    for each row execute function set_updated_at();

commit;
