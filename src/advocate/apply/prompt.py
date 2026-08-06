"""Assembling what the drafting agent is told.

The single largest change from the OpenCode harness is here, and it is a
quality decision rather than a plumbing one: **the grounding material is
preloaded, not fetched.**

Under OpenCode the agent was handed a brief that pointed at SKILL.md, and the
skill in turn told it to read the dossier and the claims file. Every one of
those reads was a choice the model could skip, quietly, and a draft written
without the dossier looks exactly like a draft written with it until someone
checks every sentence. Since the free Nemotron route carries a 1M-token context
and the whole corpus is about 85 KB, there is no reason to let the one law -
never invent - depend on the model deciding to read its own evidence.

So SKILL.md, EVIDENCE_DOSSIER.md and claims.yaml go into the system prompt
verbatim. `references/cv-research.md` deliberately does not: the skill says to
read it "when a choice needs justifying, not by default every time", and that
instruction is still worth honouring - it stays reachable with `read_file`.
"""

from __future__ import annotations

from pathlib import Path

SYSTEM_HEADER = """\
You are drafting one job application, headless, on behalf of Ali Alp Oezer.

Below, in full, are three documents. Treat them as your standing instructions and
your only source of facts:

  1. the cv-drafter skill, which is how this job is done
  2. EVIDENCE_DOSSIER.md, the graded evidence
  3. claims/claims.yaml, the claim store

They are already here. Do not spend tool calls re-reading them.

Nobody is watching this session and nobody can answer a question. Where the skill
says to ask Alp or wait for approval, decide instead, and record the decision and
its reasoning in strategy.md. The human gate has not been removed: an approval bot
sends Alp the rendered PDFs and refuses every send until he approves. Draft as
though the document goes out exactly as written.

You have five tools: read_file, write_file, list_files, render_pdf, finish.
Writes are confined to this application's folder; anything else is refused. There
is no shell - render_pdf calls the renderer directly.

Hard rules, checked mechanically after you stop:
  - Never invent. Every factual sentence traces to a dossier section or a claim id.
  - Never use an em dash. Use a plain dash.
  - Rewrite both documents end to end. They are currently verbatim copies of
    another company's application, in that company's language. Leaving any of that
    text in place is the exact failure that already happened once on this path.
  - Write strategy.md and claims-used.md. Both are required.
  - Render both documents to PDF.
  - Do not rename the folder. It is the tracking store's primary key.

Call finish last, with your closing paragraph: the angle taken, the gaps you
named, and anything about this posting Alp should look at before approving.
"""

TASK = """\
Draft the application now.

Company:      {company}
Role:         {title}
URL:          {url}
Posting text: {posting_file}   (already fetched - read this file, not the URL)
Folder:       applications/{slug}/   (already scaffolded from the house template)

The folder already contains Lebenslauf_Ali_Alp_Oezer.html and
Anschreiben_Ali_Alp_Oezer.html as copies of the house template, plus posting.md.
Start by reading the posting and the two templates, then follow the skill's
process: parse the posting and its register, do the requirement-by-requirement
gap analysis, write strategy.md, draft both documents, write claims-used.md,
render both PDFs, read your own output back, then call finish.
"""


def _read(path: Path, label: str) -> str:
    if not path.is_file():
        raise SystemExit(
            f"refusing to draft: {label} is missing at {path}. It carries the drafting "
            f"methodology or the evidence, and without it the failure would be a "
            f"plausible bad application rather than an error."
        )
    return path.read_text(encoding="utf-8")


def build_system_prompt(repo: Path, skill_dir: Path) -> str:
    """Header plus the three documents, verbatim, in the order the skill expects."""
    skill = _read(skill_dir / "SKILL.md", "cv-drafter's SKILL.md")
    dossier = _read(repo / "EVIDENCE_DOSSIER.md", "EVIDENCE_DOSSIER.md")
    claims = _read(repo / "claims" / "claims.yaml", "claims/claims.yaml")

    skill_rel = skill_dir.relative_to(repo).as_posix()
    return (
        SYSTEM_HEADER
        + f"\n\n{'=' * 70}\n# DOCUMENT 1 OF 3 - the cv-drafter skill\n"
        + f"Its own directory is {skill_rel}/. Where it refers to references/... or\n"
        + "scripts/..., those are relative to that directory and reachable with\n"
        + "read_file. Every other path it names is relative to the repository root.\n"
        + "One instruction in it is superseded: ignore its Windows render command and\n"
        + f"use the render_pdf tool.\n{'=' * 70}\n\n"
        + skill
        + f"\n\n{'=' * 70}\n# DOCUMENT 2 OF 3 - EVIDENCE_DOSSIER.md\n{'=' * 70}\n\n"
        + dossier
        + f"\n\n{'=' * 70}\n# DOCUMENT 3 OF 3 - claims/claims.yaml\n{'=' * 70}\n\n"
        + claims
    )


def build_task_prompt(*, slug: str, company: str, title: str, url: str, posting_file: str) -> str:
    return TASK.format(
        slug=slug, company=company, title=title, url=url, posting_file=posting_file
    )
