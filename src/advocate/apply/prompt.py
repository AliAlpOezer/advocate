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

Below, in full, are the documents you work from. Treat them as your standing
instructions and your only source of facts: the graded evidence in
EVIDENCE_DOSSIER.md, the claim store in claims/claims.yaml, and - where this stage
needs it - the cv-drafter skill, which is how this job is done.

They are already here. Do not spend tool calls re-reading them.

Nobody is watching this session and nobody can answer a question. Where the skill
says to ask Alp or wait for approval, decide instead, and record the decision and
its reasoning in strategy.md. The human gate has not been removed: an approval bot
sends Alp the rendered PDFs and refuses every send until he approves. Draft as
though the document goes out exactly as written.

**The work is split into four stages, and this conversation is one of them.** The
message that follows says which stage it is and what one file it produces. Do that
and only that. The stage ends when the file is right, which is checked by reading
it back off disk - not when you say so, and there is no tool for saying so.

  - Answer with tool calls. A reply with no tool call changes nothing on disk, and
    the stage will simply ask you again with a list of what is still wrong.
  - Writes are confined to this application's folder, and each stage has exactly
    one way to write. There is no shell. The PDFs are rendered by the pipeline
    after the last stage, so rendering is never your job.
  - Do not rename the folder. It is the tracking store's primary key.

Hard rules, checked mechanically the moment you write:
  - Never invent. Every factual sentence traces to a dossier section or a claim id.
    Framing, ordering and emphasis are yours to push hard; checkable facts are not.
  - Never use an em dash. Use a plain dash.
  - Both documents start as verbatim copies of another company's application, in
    that company's language. Not one word of that may survive into the version you
    write. That failure has already happened once on this path.
"""


def _read(path: Path, label: str) -> str:
    if not path.is_file():
        raise SystemExit(
            f"refusing to draft: {label} is missing at {path}. It carries the drafting "
            f"methodology or the evidence, and without it the failure would be a "
            f"plausible bad application rather than an error."
        )
    return path.read_text(encoding="utf-8")


def build_system_prompt(repo: Path, skill_dir: Path, *, include_skill: bool = True) -> str:
    """Header plus the grounding documents, verbatim, in the order the skill expects.

    `include_skill=False` drops SKILL.md, which is ~20.7 KB of *drafting
    methodology*. The claims stage does not draft: it maps finished sentences back
    to their evidence, so the methodology is dead weight there.

    **Corrected 2026-08-08.** This docstring used to justify the cut by calling
    claims "already the largest request in the pipeline", and that was measured
    false: with the skill dropped it is the *smallest*, at 85,240 chars against
    draft_letter's 118,018 - and draft_letter succeeds. Dropping the skill is
    still right on its own terms, but it is not why claims failed, and the belief
    that size was the problem is what pointed the first two attempted fixes at
    nothing. What actually fails is delivering a large tool call on that route;
    see `stages.CLAIMS_MODEL`.
    """
    dossier = _read(repo / "EVIDENCE_DOSSIER.md", "EVIDENCE_DOSSIER.md")
    claims = _read(repo / "claims" / "claims.yaml", "claims/claims.yaml")
    if not include_skill:
        return (
            SYSTEM_HEADER
            + f"\n\n{'=' * 70}\n# DOCUMENT 1 OF 2 - EVIDENCE_DOSSIER.md\n{'=' * 70}\n\n"
            + dossier
            + f"\n\n{'=' * 70}\n# DOCUMENT 2 OF 2 - claims/claims.yaml\n{'=' * 70}\n\n"
            + claims
        )

    skill = _read(skill_dir / "SKILL.md", "cv-drafter's SKILL.md")
    skill_rel = skill_dir.relative_to(repo).as_posix()
    return (
        SYSTEM_HEADER
        + f"\n\n{'=' * 70}\n# DOCUMENT 1 OF 3 - the cv-drafter skill\n"
        + f"Its own directory is {skill_rel}/. Where it refers to references/... or\n"
        + "scripts/..., those are relative to that directory and reachable with\n"
        + "read_file. Every other path it names is relative to the repository root.\n"
        + "Two of its instructions are superseded: rendering is not yours to do, and its\n"
        + "step 7 human checkpoint is the approval bot's job, after you are finished.\n"
        + f"{'=' * 70}\n\n"
        + skill
        + f"\n\n{'=' * 70}\n# DOCUMENT 2 OF 3 - EVIDENCE_DOSSIER.md\n{'=' * 70}\n\n"
        + dossier
        + f"\n\n{'=' * 70}\n# DOCUMENT 3 OF 3 - claims/claims.yaml\n{'=' * 70}\n\n"
        + claims
    )
