"""The drafting agent's tools, confined by construction.

Under the OpenCode harness the confinement was a pattern map in a config file,
and it was measured to fail open: `apply/**` silently matched nothing while
`**/apply/**` denied correctly, and an absolute path matched nothing either. A
deny rule that fails open is indistinguishable from a working one until the day
it matters, and it was never verified at all on the laptop's OpenCode version.

Here the boundary is a resolved-path check in Python. There is no pattern
dialect to get wrong and no version skew: a write outside the application's own
folder raises, and the model sees the error as a tool result.

There is also no shell. Rendering imports the renderer and calls it, so the
whole `bash` permission surface - and with it any question about whether
`git commit` is reachable - simply does not exist.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool

# Reads are allowed across the repo because drafting genuinely needs the house
# template, the master resumes and prior applications for consistency. These two
# subtrees are still refused: `apply/` is the driver's own state (the store, the
# logs, this run's brief) and `job-search/` is the hunt's databank. Nothing in
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


def build_tools(repo: Path, slug: str, state_sink: list[dict]) -> list[StructuredTool]:
    """Tools bound to one repository and one application folder.

    `state_sink` collects a record per call. The graph reads it after each tools
    node rather than parsing anything back out of the message stream.
    """
    repo = repo.resolve()
    folder = (repo / "applications" / slug).resolve()

    def _record(name: str, args: dict, ok: bool, detail: str) -> None:
        state_sink.append({"tool": name, "args": args, "ok": ok, "detail": detail})

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

    def write_file(path: str, content: str) -> str:
        """Write a UTF-8 text file. Only paths inside this application's folder are allowed."""
        try:
            target = _resolve(repo, path)
            if target != folder and folder not in target.parents:
                raise ToolError(
                    f"writes are confined to applications/{slug}/. Refused: {_rel(repo, target)}. "
                    f"The driver owns everything outside that folder, including the tracking store."
                )
            if not content.strip():
                raise ToolError("refusing to write an empty file")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except ToolError as exc:
            _record("write_file", {"path": path}, False, str(exc))
            return f"ERROR: {exc}"
        _record("write_file", {"path": path, "bytes": len(content)}, True, "written")
        return f"wrote {_rel(repo, target)} ({len(content)} chars)"

    def list_files() -> str:
        """List the files currently in this application's folder."""
        if not folder.is_dir():
            _record("list_files", {}, False, "folder missing")
            return f"ERROR: applications/{slug}/ does not exist"
        names = sorted(p.name for p in folder.iterdir())
        _record("list_files", {}, True, f"{len(names)} entries")
        return "\n".join(names) if names else "(empty)"

    def render_pdf(html_file: str) -> str:
        """Render one HTML file in this application's folder to a PDF beside it."""
        # Imported here, not at module scope: it resolves a Chrome binary at call
        # time and a missing browser must surface as a failed tool call the model
        # can report, not as an ImportError that kills the process before any
        # drafting has happened.
        from advocate.render.build_pdf import render

        try:
            target = _resolve(repo, html_file)
            if folder not in target.parents:
                raise ToolError(f"can only render files in applications/{slug}/")
            if not target.is_file():
                raise ToolError(f"no such file: {_rel(repo, target)}")
            out = target.with_suffix(".pdf")
            render(target, out)
            if not out.is_file():
                raise ToolError("the renderer reported success but produced no PDF")
            size = out.stat().st_size
        except ToolError as exc:
            _record("render_pdf", {"html_file": html_file}, False, str(exc))
            return f"ERROR: {exc}"
        except Exception as exc:  # a broken renderer is the model's problem to report
            _record("render_pdf", {"html_file": html_file}, False, repr(exc))
            return f"ERROR: rendering failed: {exc}"
        _record("render_pdf", {"html_file": html_file}, True, f"{size} bytes")
        return f"rendered {out.name} ({size} bytes)"

    def finish(summary: str) -> str:
        """Declare the application complete. Call this last, with your closing paragraph."""
        _record("finish", {}, True, summary[:200])
        return "recorded"

    return [
        StructuredTool.from_function(read_file),
        StructuredTool.from_function(write_file),
        StructuredTool.from_function(list_files),
        StructuredTool.from_function(render_pdf),
        StructuredTool.from_function(finish),
    ]
