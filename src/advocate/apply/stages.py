"""The drafting job, cut into stages small enough for a model to finish.

Measured twice on 2026-08-06: asked for a whole application in one conversation,
nemotron-3-ultra reads the posting and both templates, writes a correct
`strategy.md`, and then stops emitting tool calls. Six turns and three nudges
changed nothing - both runs stalled at exactly four tool calls. The loop was not
the problem; the horizon was.

So the single agent node becomes a sequence of small ones, each a fresh short
conversation with one file to write:

    analyse -> draft_cv -> draft_letter -> claims -> render

Two properties fall out of that, and both are the point:

  - **"Did it work" is a file comparison, not a judgement.** Every stage carries
    a `problems()` that reads the folder and says what is still wrong. The model
    does not get to declare itself done, which is why there is no `finish` tool
    any more. A stage whose problems are already empty when it starts is skipped
    outright, so a retry resumes where the last attempt stopped instead of
    redrafting what already exists.
  - **The checks are the ones verify.ts would fail on later**, moved forward to
    where they are still cheap to fix: a leftover template marker, an em dash, an
    `<img>` that does not resolve. Failing them nudges the model with the specific
    line rather than failing the run an hour later. verify.ts stays exactly as it
    is; it is the independent cross-check, not this.

`render` is not in this file. It never needed a model at all, and taking it away
from the agent removes the two tool calls that both stalled runs died before
reaching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CV = "Lebenslauf_Ali_Alp_Oezer.html"
LETTER = "Anschreiben_Ali_Alp_Oezer.html"
STRATEGY = "strategy.md"
CLAIMS_USED = "claims-used.md"

# The folder `new-application.sh` copies from, and the company names that have
# been drafted against before. Both mirror verify.ts deliberately: the two sides
# must agree on what "the scaffold was never edited" means, or a draft passes one
# gate and fails the other for reasons nobody can reconcile.
TEMPLATE_SLUG = "SSI_Schaefer_Bewerbung"
TEMPLATE_MARKERS = ("SSI", "Schäfer", "Schaefer", "Platinion", "Temedica")

# Same thresholds as verify.ts, for the same reason.
MIN_STRATEGY_BYTES = 120
MIN_CLAIMS_USED_BYTES = 300

_NOISE_WORDS = {
    "gmbh", "ag", "se", "kg", "mbh", "co", "group", "the", "and", "at", "inc", "ltd",
}
_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)

# A dossier section, or a claim id - which always has at least two dots
# (`edu.tum_msc.active_enrollment`). Deliberately stricter than verify.ts's
# single-dot version, which a filename satisfies: a `claims-used.md` consisting
# of one run-on header line passed that check on 2026-08-07 while citing nothing.
_CITATION = re.compile(r"§\s*\d|\b[a-z][a-z0-9_]*\.[a-z0-9_]+\.[a-z0-9_]+\b")

# The hand-validated Temedica map is 6,875 bytes over 72 lines. The degenerate one
# that forced a write out of a stalling model was 706 bytes on a single line. The
# thresholds sit between the two and closer to the floor, because this gate exists
# to catch a non-answer, not to grade thoroughness.
MIN_CLAIMS_USED_LINES = 10
MIN_CLAIMS_USED_CITATIONS = 5


def significant_words(company: str) -> list[str]:
    """The parts of a company name worth matching on. Mirrors verify.ts."""
    parts = re.split(r"[^A-Za-zÀ-ÿ0-9]+", company)
    return [w.lower() for w in parts if len(w) >= 3 and w.lower() not in _NOISE_WORDS]


@dataclass(frozen=True)
class Application:
    """One application being drafted, and the facts every stage needs about it."""

    repo: Path
    slug: str
    company: str
    title: str
    url: str
    posting_file: str

    @property
    def folder(self) -> Path:
        return self.repo / "applications" / self.slug

    @property
    def template_dir(self) -> Path:
        return self.repo / "applications" / TEMPLATE_SLUG

    def read(self, name: str) -> str:
        """Contents of a file in this application's folder, or "" if absent."""
        path = self.folder / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def posting(self) -> str:
        path = self.repo / self.posting_file
        if not path.is_file():
            raise SystemExit(
                f"refusing to draft: the posting is missing at {path}. The driver fetches it "
                f"before starting, so its absence is a driver failure, not a drafting one."
            )
        return path.read_text(encoding="utf-8")

    def template(self, name: str) -> str:
        path = self.template_dir / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""


def _document_problems(app: Application, name: str, *, needs_company: bool) -> list[str]:
    """What is still wrong with one drafted HTML document.

    Every check here has already failed in this repo at least once, and each is
    phrased as an instruction because the text goes straight into the nudge the
    model reads next.
    """
    html = app.read(name)
    if not html:
        return [f"{name} does not exist"]

    problems: list[str] = []
    wanted = significant_words(app.company)

    if html == app.template(name):
        problems.append(
            f"{name} is still byte-identical to the {TEMPLATE_SLUG} template it was copied "
            f"from - none of it has been rewritten yet"
        )

    for marker in TEMPLATE_MARKERS:
        if marker.lower() in wanted:
            continue
        if re.search(rf"\b{re.escape(marker)}\b", html, re.I):
            problems.append(
                f'{name} still contains "{marker}", left over from the template - remove every '
                f"trace of the previous employer"
            )

    if "—" in html:
        problems.append(
            f"{name} contains an em dash. Alp's rule is a period, a comma or a plain hyphen"
        )

    for src in _IMG_SRC.findall(html):
        if re.match(r"^(https?:|data:)", src, re.I):
            continue
        if not (app.folder / src).resolve().is_file():
            problems.append(
                f"{name} references an image that does not resolve: {src}. Keep the template's "
                f"photo tag exactly as it was, path included"
            )

    if needs_company and wanted and not any(w in html.lower() for w in wanted):
        problems.append(
            f"{name} never names {app.company}, and a cover letter has to name who it is "
            f"addressed to"
        )

    return problems


def analyse_problems(app: Application) -> list[str]:
    text = app.read(STRATEGY).strip()
    if not text:
        return [f"{STRATEGY} has not been written"]
    if len(text) < MIN_STRATEGY_BYTES:
        return [
            f"{STRATEGY} is only {len(text)} characters - too short to state an angle, the "
            f"claims it leads with, and the gaps it concedes"
        ]
    return []


def cv_problems(app: Application) -> list[str]:
    return _document_problems(app, CV, needs_company=False)


def letter_problems(app: Application) -> list[str]:
    return _document_problems(app, LETTER, needs_company=True)


def claims_problems(app: Application) -> list[str]:
    text = app.read(CLAIMS_USED).strip()
    if not text:
        return [f"{CLAIMS_USED} has not been written"]
    if len(text) < MIN_CLAIMS_USED_BYTES:
        return [
            f"{CLAIMS_USED} is only {len(text)} characters - too short to be a bullet-by-bullet "
            f"map of the two documents"
        ]

    problems: list[str] = []
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_CLAIMS_USED_LINES:
        problems.append(
            f"{CLAIMS_USED} is {len(lines)} line(s). It is one line per claim across two "
            f"documents, so it runs to dozens - write the map, not a description of it"
        )
    citations = {m.group(0) for m in _CITATION.finditer(text)}
    if len(citations) < MIN_CLAIMS_USED_CITATIONS:
        problems.append(
            f"{CLAIMS_USED} cites {len(citations)} distinct source(s). Every line needs the "
            f"dossier section (§4.1) or claim id (edu.tum_msc.active_enrollment) it comes from"
        )
    return problems


ANALYSE_TASK = """\
Stage 1 of 4: the gap analysis. One tool call, then you are done with this stage.

Company:  {company}
Role:     {title}
URL:      {url}

Write applications/{slug}/{strategy} with write_file. Nothing else. Do not draft
either document yet, and do not reply with prose - the next stage cannot start
until this file exists.

Follow the skill's analysis steps and put their output in the file:
  - the posting's register and language, and which language the application is in
  - a requirement-by-requirement table: each requirement, the claim id or dossier
    section that covers it, and its grade
  - every requirement nothing covers, named as a gap, with how the documents
    handle it. Never close a gap by inventing something.
  - the angle: what this application leads with, and what it leaves out

This file is what Alp reads on the approval card before he ever opens the PDFs,
so it is the argument for the application, not a summary of the posting.

=== the posting, already fetched ===
{posting}
"""

CV_TASK = """\
Stage 2 of 4: the Lebenslauf. One tool call, then you are done with this stage.

Company:  {company}
Role:     {title}

Call write_document with the finished contents of the CV's <body>. Send the body
only - everything from <header class="kopf"> to the last section. The page shell,
the <head> and all the CSS are kept for you and must not be sent back; they are
the house design and rewriting them breaks the PDF layout.

Rules for this document, all of them checked mechanically the moment you write:
  - German, and a German CV does not name the employer it is sent to. Tailoring
    happens through ordering, wording and emphasis.
  - Keep the photo tag exactly as it is, path included.
  - Keep the structure and the CSS class names. This is a layout that renders to
    a known page count; invented markup does not.
  - Every factual sentence traces to the dossier or a claim id. Reorder, reword
    and re-emphasise as hard as you like. Do not add a fact that is not there.
  - No em dash anywhere.

Aim at what {strategy} said, which is reproduced below with the posting and the
current template.

=== {strategy}, written in stage 1 ===
{strategy_text}

=== the posting ===
{posting}

=== the current Lebenslauf body, still the template's ===
{body}
"""

LETTER_TASK = """\
Stage 3 of 4: the Anschreiben. One tool call, then you are done with this stage.

Company:  {company}
Role:     {title}
URL:      {url}

Call write_document with the finished contents of the cover letter's <body>. Body
only - the shell and the CSS are kept for you.

Rules, all checked mechanically the moment you write:
  - It must name {company} and the role it is applying for.
  - Not one word of the previous employer's letter survives. It is a different
    company, and often a different language.
  - The Lebenslauf is now written and is reproduced below. The letter argues; it
    does not repeat the CV line by line.
  - Every factual sentence traces to the dossier or a claim id.
  - No em dash anywhere.

=== {strategy}, written in stage 1 ===
{strategy_text}

=== the posting ===
{posting}

=== the finished Lebenslauf body, written in stage 2 ===
{cv_body}

=== the current Anschreiben body, still the template's ===
{body}
"""

CLAIMS_TASK = """\
Stage 4 of 4: the grounding record. One tool call, then the run is over.

Write applications/{slug}/{claims_used} with write_file: a bullet-by-bullet map
from the two finished documents back to the evidence, so a reader can check any
sentence without asking you.

One line per substantive claim in either document:
  - the sentence or bullet, quoted or shortened
  - which document it is in
  - the claim id or dossier section it comes from, and that claim's grade
  - for anything framed rather than stated outright, one line on why the framing
    is still true

End with the gaps: every posting requirement nothing covers, and how the
documents handled it. This file is the manual stand-in for the grounding check,
so an unsourceable sentence is a finding, not something to leave out. If you find
one, say so here plainly and name the document it is in.

=== the finished Lebenslauf body ===
{cv_body}

=== the finished Anschreiben body ===
{letter_body}
"""


@dataclass(frozen=True)
class Stage:
    """One node of the pipeline: a task, the tools for it, and how to tell it is done."""

    name: str
    # Which write tool this stage gets. "file" is the confined markdown writer,
    # "document" is the body-splicing HTML writer bound to `document`.
    writer: str
    build_task: Callable[[Application], str]
    problems: Callable[[Application], list[str]]
    # Small on purpose. Every stage here is one tool call's worth of work, so a
    # stage that has not finished in five turns is stuck, not slow.
    max_turns: int = 5
    document: str | None = None
    # Whether cv-drafter's SKILL.md is preloaded for this stage. It is drafting
    # methodology, so the stage that only maps finished sentences to their sources
    # does not need it - and that stage is otherwise the largest request in the
    # pipeline, which is the opposite of what splitting the job was for.
    needs_skill: bool = True


def _analyse_task(app: Application) -> str:
    return ANALYSE_TASK.format(
        company=app.company,
        title=app.title,
        url=app.url,
        slug=app.slug,
        strategy=STRATEGY,
        posting=app.posting(),
    )


def _cv_task(app: Application) -> str:
    from advocate.apply.documents import body_of

    return CV_TASK.format(
        company=app.company,
        title=app.title,
        strategy=STRATEGY,
        strategy_text=app.read(STRATEGY),
        posting=app.posting(),
        body=body_of(app.read(CV)),
    )


def _letter_task(app: Application) -> str:
    from advocate.apply.documents import body_of

    return LETTER_TASK.format(
        company=app.company,
        title=app.title,
        url=app.url,
        strategy=STRATEGY,
        strategy_text=app.read(STRATEGY),
        posting=app.posting(),
        cv_body=body_of(app.read(CV)),
        body=body_of(app.read(LETTER)),
    )


def _claims_task(app: Application) -> str:
    from advocate.apply.documents import body_of

    return CLAIMS_TASK.format(
        slug=app.slug,
        claims_used=CLAIMS_USED,
        cv_body=body_of(app.read(CV)),
        letter_body=body_of(app.read(LETTER)),
    )


DRAFTING_STAGES: tuple[Stage, ...] = (
    Stage("analyse", "file", _analyse_task, analyse_problems),
    Stage("draft_cv", "document", _cv_task, cv_problems, document=CV),
    Stage("draft_letter", "document", _letter_task, letter_problems, document=LETTER),
    Stage("claims", "file", _claims_task, claims_problems, needs_skill=False),
)
