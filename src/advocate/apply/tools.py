"""The drafting agent's tools, confined by construction and cut per stage.

Under the OpenCode harness the confinement was a pattern map in a config file,
and it was measured to fail open: `apply/**` silently matched nothing while
`**/apply/**` denied correctly, and an absolute path matched nothing either. A
deny rule that fails open is indistinguishable from a working one until the day
it matters, and it was never verified at all on the laptop's OpenCode version.

Here the boundary is a resolved-path check in Python. There is no pattern
dialect to get wrong and no version skew: a write outside the application's own
folder raises, and the model sees the error as a tool result.

There is also no shell. Rendering imports the renderer and calls it, and since
the split it is not even a tool - it is a graph node, so the whole `bash`
permission surface and any question about reaching `git commit` simply does not
exist.

Each stage gets only the tools its one job needs. The stage that writes the CV
cannot write the cover letter, and no stage can write both. That is not
tidiness: a model with one write target and one task cannot half-finish the
application in a way that has to be untangled afterwards.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool

from advocate.apply.documents import DocumentError, body_of, normalise_body, splice_body
from advocate.apply.stages import CV, LETTER, Application, Stage

# Reads are allowed across the repo because drafting genuinely needs the house
# template, the master resumes and prior applications for consistency. These two
# subtrees are still refused: `apply/` is the driver's own state (the store, the
# logs, this run's reports) and `job-search/` is the hunt's databank. Nothing in
# the drafting job needs either, and both have been corrupted by an agent before.
READ_DENIED = ("apply", "job-search")

MAX_READ_BYTES = 400_000


class ToolError(Exception):
    """Raised into the model as a tool result, never up into the loop."""


def _resolve(repo: Path, raw: str) -> Path:
    """Repo-relative or absolute, resolved and proven to be inside the repo.

    `strict=False` so a path that does not exist yet still resolves - writing a
    new file is the common case. `..` is neutralised by resolution rather than
    by string inspection, which is what makes this hard to talk past.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != repo and repo not in resolved.parents:
        raise ToolError(f"path escapes the repository: {raw}")
    return resolved


def _rel(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def build_read_tools(app: Application, sink: list[dict]) -> list[StructuredTool]:
    """read_file and list_files. Every stage gets these; none of them needs to.

    The grounding material is already in the system prompt, so these exist for
    the things it deliberately leaves out - `references/cv-research.md`, a prior
    application worth matching in tone - and for a model that wants to check its
    own output. A stage that uses neither is working as intended.
    """
    repo = app.repo

    def _record(name: str, args: dict, ok: bool, detail: str) -> None:
        sink.append({"tool": name, "args": args, "ok": ok, "detail": detail})

    def read_file(path: str) -> str:
        """Read a UTF-8 text file from the repository. Paths are repo-relative."""
        try:
            target = _resolve(repo, path)
            rel = _rel(repo, target)
            if rel.split("/", 1)[0] in READ_DENIED:
                raise ToolError(
                    f"{rel} is off limits: apply/ is the driver's state and job-search/ is the "
                    f"hunt's databank. Neither is part of drafting."
                )
            if not target.is_file():
                raise ToolError(f"no such file: {rel}")
            if target.stat().st_size > MAX_READ_BYTES:
                raise ToolError(f"{rel} is larger than {MAX_READ_BYTES} bytes")
            body = target.read_text(encoding="utf-8")
        except ToolError as exc:
            _record("read_file", {"path": path}, False, str(exc))
            return f"ERROR: {exc}"
        _record("read_file", {"path": path}, True, f"{len(body)} chars")
        return body

    def list_files() -> str:
        """List the files currently in this application's folder."""
        if not app.folder.is_dir():
            _record("list_files", {}, False, "folder missing")
            return f"ERROR: applications/{app.slug}/ does not exist"
        names = sorted(p.name for p in app.folder.iterdir())
        _record("list_files", {}, True, f"{len(names)} entries")
        return "\n".join(names) if names else "(empty)"

    return [
        StructuredTool.from_function(read_file),
        StructuredTool.from_function(list_files),
    ]


def build_write_file_tool(app: Application, sink: list[dict]) -> StructuredTool:
    """The markdown writer: strategy.md, claims-used.md, anything that is not a document.

    HTML is refused here even though the path would be allowed. The two documents
    have a stage of their own with a tool that keeps the page shell, and a model
    that writes one from this stage would be writing it without that protection
    and outside the stage whose checks would have caught it.
    """
    repo, folder, slug = app.repo, app.folder.resolve(), app.slug

    def write_file(path: str, content: str) -> str:
        """Write a UTF-8 text file. Only paths inside this application's folder are allowed."""
        try:
            target = _resolve(repo, path)
            if target != folder and folder not in target.parents:
                raise ToolError(
                    f"writes are confined to applications/{slug}/. Refused: {_rel(repo, target)}. "
                    f"The driver owns everything outside that folder, including the tracking store."
                )
            if target.suffix.lower() in (".html", ".htm"):
                raise ToolError(
                    f"{target.name} is one of the two documents, and it is not this stage's job. "
                    f"Each document is written in its own stage with write_document."
                )
            if not content.strip():
                raise ToolError("refusing to write an empty file")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except ToolError as exc:
            sink.append({"tool": "write_file", "args": {"path": path}, "ok": False, "detail": str(exc)})
            return f"ERROR: {exc}"
        sink.append(
            {
                "tool": "write_file",
                "args": {"path": path, "bytes": len(content)},
                "ok": True,
                "detail": "written",
            }
        )
        return f"wrote {_rel(repo, target)} ({len(content)} chars)"


    return StructuredTool.from_function(write_file)


def build_document_tool(app: Application, sink: list[dict], filename: str) -> StructuredTool:
    """The body-splicing writer, bound to exactly one of the two documents.

    The target is closed over rather than passed, so there is no argument to get
    wrong and no way for the CV stage to write the cover letter.
    """
    target = (app.folder / filename).resolve()
    shell_source = target if target.is_file() else app.template_dir / filename
    template_body = body_of(app.template(filename))
    # Proportional rather than absolute so it still means something if the house
    # template changes. It only has to catch a truncated or placeholder body; the
    # stage's own checks judge whether the content is real.
    min_chars = max(400, int(len(template_body) * 0.4))

    label = "Lebenslauf" if filename == CV else "Anschreiben" if filename == LETTER else filename

    def write_document(body: str) -> str:
        """Write the finished <body> of this stage's document. Send the body only, no <head> or CSS."""
        try:
            cleaned = normalise_body(body)
            if len(cleaned) < min_chars:
                raise ToolError(
                    f"that body is {len(cleaned)} characters and the {label} needs at least "
                    f"{min_chars}. Send the whole finished body in one call, not an excerpt "
                    f"or a description of the changes."
                )
            if not shell_source.is_file():
                raise ToolError(f"no page shell to write into: {filename} is missing")
            spliced = splice_body(shell_source.read_text(encoding="utf-8"), cleaned)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(spliced, encoding="utf-8")
        except (ToolError, DocumentError) as exc:
            sink.append(
                {"tool": "write_document", "args": {"file": filename}, "ok": False, "detail": str(exc)}
            )
            return f"ERROR: {exc}"
        sink.append(
            {
                "tool": "write_document",
                "args": {"file": filename, "bodyChars": len(cleaned)},
                "ok": True,
                "detail": f"{len(spliced)} chars written",
            }
        )
        return (
            f"wrote applications/{app.slug}/{filename} - {len(cleaned)} characters of body "
            f"spliced into the house shell ({len(spliced)} total)"
        )

    return StructuredTool.from_function(write_document)


def tools_for(stage: Stage, app: Application, sink: list[dict]) -> list[StructuredTool]:
    """The tool set for one stage: reads, plus exactly one way to write."""
    tools = build_read_tools(app, sink)
    if stage.writer == "document":
        assert stage.document, "a document stage must name its document"
        tools.append(build_document_tool(app, sink, stage.document))
    else:
        tools.append(build_write_file_tool(app, sink))
    return tools


def render_documents(app: Application, sink: list[dict]) -> list[str]:
    """Render both documents to PDF. Deterministic, and never a model's decision.

    This was two of the agent's tool calls and it is the point in the run both
    stalled attempts died before reaching. Rendering never needed judgement: the
    two filenames are fixed, the renderer takes an HTML path and an output path,
    and a failure here is an environment problem (no Chrome) rather than
    something a model could correct.
    """
    # Imported here, not at module scope: it resolves a Chrome binary at call
    # time, and on a host without one that must surface as a failed render after
    # the documents exist, not as an ImportError before any drafting happens.
    from advocate.render.build_pdf import render

    problems: list[str] = []
    for filename in (CV, LETTER):
        source = app.folder / filename
        if not source.is_file():
            problems.append(f"{filename} does not exist, so there is nothing to render")
            continue
        out = source.with_suffix(".pdf")
        try:
            render(source, out)
            if not out.is_file():
                raise RuntimeError("the renderer reported success but produced no PDF")
            size = out.stat().st_size
        except Exception as exc:  # noqa: BLE001 - reported, not raised: the run has a report
            problems.append(f"rendering {filename} failed: {exc}")
            sink.append(
                {"tool": "render", "args": {"file": filename}, "ok": False, "detail": str(exc)}
            )
            continue
        sink.append(
            {"tool": "render", "args": {"file": filename}, "ok": True, "detail": f"{size} bytes"}
        )
    return problems
