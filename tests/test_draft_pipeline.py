"""The drafting pipeline, driven by a stub model. No network, no browser.

Run it directly - there is no test runner pinned, and adding one would change
what has to be installed on the box:

    py -m tests.test_draft_pipeline          (from the repo root, with src/ on the path)
    PYTHONPATH=src python tests/test_draft_pipeline.py

The cases here are the failures this pipeline was built in response to, not
hypotheticals. A model that narrates instead of acting ended a run that was three
quarters done (2026-08-06). A model that stalls after the analysis step wasted two
whole runs the same day. A document that came back with the template's text still
in it went out to a recruiter in 2026-08-05. Each of those is one test below, and
each one has to fail here rather than an hour into a real draft.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.messages import AIMessage  # noqa: E402

import advocate.render.build_pdf as build_pdf  # noqa: E402
from advocate.apply.documents import body_of, normalise_body, splice_body  # noqa: E402
from advocate.apply.graph import build_graph  # noqa: E402
from advocate.apply.stages import CLAIMS_USED, CV, LETTER, STRATEGY, TEMPLATE_SLUG, Application  # noqa: E402

TEMPLATE_HTML = """<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>{doc} - Ali Alp Ozer</title>
<style>body{{ font-size:9pt; }} .foto{{ width:32mm; }}</style>
</head>
<body>
  <header class="kopf">
    <h1>Ali Alp Ozer</h1>
    <img class="foto" src="../../assets/foto.jpg" alt="Ali Alp Ozer">
  </header>
  <p>Bewerbung bei SSI Schaefer, geschrieben fuer eine andere Stelle. {filler}</p>
</body>
</html>
"""

GOOD_CV_BODY = """  <header class="kopf">
    <h1>Ali Alp Ozer</h1>
    <img class="foto" src="../../assets/foto.jpg" alt="Ali Alp Ozer">
  </header>
  <p>Softwareentwickler mit gut drei Jahren Praxis, zuletzt an LLM- und
  Agentensystemen. """ + ("Belegte Erfahrung aus dem Dossier. " * 40) + "</p>"

GOOD_LETTER_BODY = """  <h1>Anschreiben</h1>
  <p>Sehr geehrtes Team von Contoso Analytics, """ + ("hier steht ein Satz. " * 40) + "</p>"

GOOD_STRATEGY = "# Strategie\n\n" + ("Winkel, fuehrende Claims und benannte Luecken. " * 8)
GOOD_CLAIMS_USED = "# Claims used\n\n" + "\n".join(
    f"| Punkt {i} | §{i}.1 / exp.flexus.claim_{i} | strong |" for i in range(1, 13)
)


# ---------------------------------------------------------------- fixtures


def make_repo(tmp: Path, *, slug: str = "Contoso_Analytics_Bewerbung") -> Application:
    """A repository shaped like advocate-data, with one scaffolded application."""
    (tmp / "assets").mkdir()
    (tmp / "assets" / "foto.jpg").write_bytes(b"jpegish")
    (tmp / "claims").mkdir()
    (tmp / "claims" / "claims.yaml").write_text("claims: []\n", encoding="utf-8")
    (tmp / "EVIDENCE_DOSSIER.md").write_text("# Dossier\n", encoding="utf-8")

    template = tmp / "applications" / TEMPLATE_SLUG
    template.mkdir(parents=True)
    for name, doc in ((CV, "Lebenslauf"), (LETTER, "Anschreiben")):
        (template / name).write_text(
            TEMPLATE_HTML.format(doc=doc, filler="Fuellsatz. " * 60), encoding="utf-8"
        )

    folder = tmp / "applications" / slug
    folder.mkdir(parents=True)
    for name in (CV, LETTER):
        shutil.copyfile(template / name, folder / name)
    (folder / "posting.md").write_text("# Werkstudent Data Science\n", encoding="utf-8")

    return Application(
        repo=tmp,
        slug=slug,
        company="Contoso Analytics GmbH",
        title="Werkstudent Data Science",
        url="https://example.invalid/job",
        posting_file=f"applications/{slug}/posting.md",
    )


class StubChat:
    """A scripted model. Each script entry is one turn: tool calls, or prose."""

    def __init__(self, script: list[object]):
        self.script = list(script)
        self.attempts: list[str] = []
        self.calls: list[list[str]] = []  # tool names offered, per turn
        self.turns = 0

    def invoke(self, messages, tools=None):
        self.turns += 1
        self.calls.append(sorted(t.name for t in (tools or [])))
        if not self.script:
            raise AssertionError("the stub ran out of script - the loop asked for another turn")
        step = self.script.pop(0)
        if isinstance(step, str):
            return AIMessage(content=step)
        name, args = step
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"call_{self.turns}", "type": "tool_call"}],
        )


def fake_render(src_html: Path, out_pdf: Path) -> None:
    out_pdf.write_bytes(b"%PDF-1.4 stub\n" + src_html.read_bytes()[:64])


def run(app: Application, chat: StubChat, **kwargs):
    sink: list[dict] = []
    graph = build_graph(chat, app, sink, lambda stage: f"SYSTEM[{stage.name}]", **kwargs)
    return graph.invoke({"slug": app.slug, "turns": 0, "nudges": 0}, {"recursion_limit": 60})


def stage(final: dict, name: str) -> dict:
    found = [s for s in final["stages"] if s["stage"] == name]
    assert found, f"no record for stage {name}: {[s['stage'] for s in final['stages']]}"
    return found[0]


HAPPY_SCRIPT = [
    ("write_file", {"path": f"applications/SLUG/{STRATEGY}", "content": GOOD_STRATEGY}),
    ("write_document", {"body": GOOD_CV_BODY}),
    ("write_document", {"body": GOOD_LETTER_BODY}),
    ("write_file", {"path": f"applications/SLUG/{CLAIMS_USED}", "content": GOOD_CLAIMS_USED}),
]


def script_for(slug: str, steps=HAPPY_SCRIPT) -> list[object]:
    out: list[object] = []
    for step in steps:
        if isinstance(step, str):
            out.append(step)
            continue
        name, args = step
        args = {k: (v.replace("SLUG", slug) if k == "path" else v) for k, v in args.items()}
        out.append((name, args))
    return out


# ------------------------------------------------------------------- cases


def test_happy_path(tmp: Path) -> None:
    app = make_repo(tmp)
    chat = StubChat(script_for(app.slug))
    final = run(app, chat)

    assert not final.get("failed"), final.get("failed")
    assert [s["stage"] for s in final["stages"]] == [
        "analyse", "draft_cv", "draft_letter", "claims", "render",
    ]
    assert all(s["ok"] for s in final["stages"])

    # One turn per stage. A finished stage that spends another is paying for a
    # closing pleasantry with a full copy of the preloaded corpus.
    assert final["turns"] == 4, final["turns"]
    assert final["nudges"] == 0

    for name in (CV, LETTER):
        assert (app.folder / name).with_suffix(".pdf").is_file()
        assert app.read(name) != app.template(name)
        # The shell survived the splice; only the body changed.
        assert "<style>" in app.read(name)
    assert app.read(STRATEGY) and app.read(CLAIMS_USED)


def test_each_stage_gets_only_its_own_write_tool(tmp: Path) -> None:
    app = make_repo(tmp)
    chat = StubChat(script_for(app.slug))
    run(app, chat)

    assert chat.calls[0] == ["list_files", "read_file", "write_file"]
    assert chat.calls[1] == ["list_files", "read_file", "write_document"]
    assert chat.calls[2] == ["list_files", "read_file", "write_document"]
    assert chat.calls[3] == ["list_files", "read_file", "write_file"]



def test_narration_fails_the_stage_and_stops_the_pipeline(tmp: Path) -> None:
    """The 2026-08-06 stall: prose instead of tool calls, forever."""
    app = make_repo(tmp)
    chat = StubChat(["I will now write the strategy."] * 6)
    final = run(app, chat, max_turns=3)

    assert final["failed"] == "analyse"
    assert [s["stage"] for s in final["stages"]] == ["analyse"]
    assert stage(final, "analyse")["turns"] == 3
    assert stage(final, "analyse")["nudges"] == 2  # one per re-entry, not after the last turn
    assert "has not been written" in stage(final, "analyse")["problems"][0]
    # Nothing downstream ran, so nothing was rendered from a folder with no draft.
    assert not (app.folder / CV).with_suffix(".pdf").exists()


def test_a_bad_write_is_nudged_with_the_specific_problem(tmp: Path) -> None:
    """An em dash, Alp's rule. Caught at the stage rather than by verify.ts later."""
    app = make_repo(tmp)
    bad = GOOD_CV_BODY.replace("Praxis,", "Praxis —")
    chat = StubChat(
        script_for(app.slug, [
            ("write_file", {"path": f"applications/SLUG/{STRATEGY}", "content": GOOD_STRATEGY}),
            ("write_document", {"body": bad}),
            ("write_document", {"body": GOOD_CV_BODY}),
            ("write_document", {"body": GOOD_LETTER_BODY}),
            ("write_file", {"path": f"applications/SLUG/{CLAIMS_USED}", "content": GOOD_CLAIMS_USED}),
        ])
    )
    final = run(app, chat)

    assert not final.get("failed")
    assert stage(final, "draft_cv")["nudges"] == 1
    assert "—" not in app.read(CV)


def test_a_prose_turn_is_nudged_rather_than_ending_the_stage(tmp: Path) -> None:
    """A reply with no tool call is a wasted turn, not the end of the stage."""
    app = make_repo(tmp)
    chat = StubChat(
        script_for(app.slug, [
            ("write_file", {"path": f"applications/SLUG/{STRATEGY}", "content": GOOD_STRATEGY}),
            "Here is what I would put in the Lebenslauf...",
            ("write_document", {"body": GOOD_CV_BODY}),
            ("write_document", {"body": GOOD_LETTER_BODY}),
            ("write_file", {"path": f"applications/SLUG/{CLAIMS_USED}", "content": GOOD_CLAIMS_USED}),
        ])
    )
    final = run(app, chat)

    assert not final.get("failed")
    assert stage(final, "draft_cv")["turns"] == 2


def test_a_retry_resumes_instead_of_redrafting(tmp: Path) -> None:
    """Attempt 2 of a draft that got as far as the CV starts at the cover letter."""
    app = make_repo(tmp)
    (app.folder / STRATEGY).write_text(GOOD_STRATEGY, encoding="utf-8")
    (app.folder / CV).write_text(
        splice_body(app.template(CV), GOOD_CV_BODY), encoding="utf-8"
    )

    chat = StubChat(
        script_for(app.slug, [
            ("write_document", {"body": GOOD_LETTER_BODY}),
            ("write_file", {"path": f"applications/SLUG/{CLAIMS_USED}", "content": GOOD_CLAIMS_USED}),
        ])
    )
    final = run(app, chat)

    assert not final.get("failed")
    assert stage(final, "analyse")["skipped"] and stage(final, "draft_cv")["skipped"]
    assert final["turns"] == 2, "the finished stages cost a model call"


def test_a_letter_that_never_names_the_company_is_not_finished(tmp: Path) -> None:
    app = make_repo(tmp)
    nameless = "  <h1>Anschreiben</h1>\n  <p>" + ("Sehr geehrte Damen und Herren. " * 40) + "</p>"
    chat = StubChat(
        script_for(app.slug, [
            ("write_file", {"path": f"applications/SLUG/{STRATEGY}", "content": GOOD_STRATEGY}),
            ("write_document", {"body": GOOD_CV_BODY}),
            ("write_document", {"body": nameless}),
            ("write_document", {"body": nameless}),
        ])
    )
    final = run(app, chat, max_turns=2)

    assert final["failed"] == "draft_letter"
    assert any("never names" in p for p in stage(final, "draft_letter")["problems"])


def test_template_text_left_behind_is_not_finished(tmp: Path) -> None:
    app = make_repo(tmp)
    leftover = GOOD_CV_BODY + "<p>Bewerbung bei SSI Schaefer.</p>"
    chat = StubChat(
        script_for(app.slug, [
            ("write_file", {"path": f"applications/SLUG/{STRATEGY}", "content": GOOD_STRATEGY}),
            ("write_document", {"body": leftover}),
            ("write_document", {"body": leftover}),
        ])
    )
    final = run(app, chat, max_turns=2)

    assert final["failed"] == "draft_cv"
    problems = " ".join(stage(final, "draft_cv")["problems"])
    assert "SSI" in problems and "Schaefer" in problems


def test_write_file_refuses_the_documents_and_escapes(tmp: Path) -> None:
    from advocate.apply.tools import build_write_file_tool

    app = make_repo(tmp)
    sink: list[dict] = []
    tool = build_write_file_tool(app, sink)

    refused = tool.invoke({"path": f"applications/{app.slug}/{CV}", "content": "<html></html>"})
    assert "write_document" in refused
    assert tool.invoke({"path": "claims/claims.yaml", "content": "x"}).startswith("ERROR")
    assert tool.invoke({"path": "../escape.md", "content": "x"}).startswith("ERROR")
    assert app.read(CV) == app.template(CV), "a refused write must not touch the file"


def test_a_whole_document_sent_to_write_document_is_accepted(tmp: Path) -> None:
    """Models send the full page perhaps one time in ten. Cheaper to read than to argue."""
    app = make_repo(tmp)
    from advocate.apply.tools import build_document_tool

    sink: list[dict] = []
    tool = build_document_tool(app, sink, CV)
    whole = splice_body(app.template(CV), GOOD_CV_BODY).replace("<style>", "<style>/* theirs */")
    assert tool.invoke({"body": "```html\n" + whole + "\n```"}).startswith("wrote ")

    written = app.read(CV)
    assert "/* theirs */" not in written, "the model's shell must not replace the house one"
    assert GOOD_CV_BODY.strip().splitlines()[0].strip() in written


def test_document_helpers() -> None:
    assert body_of("<html><body>\n<p>x</p>\n</body></html>") == "<p>x</p>"
    assert body_of("<p>bare</p>") == "<p>bare</p>"
    assert normalise_body("```html\n<p>x</p>\n```") == "<p>x</p>"
    assert splice_body("<head>H</head><body>old</body>", "new").endswith("new\n</body>")


# -------------------------------------------------------------------- main


def main() -> int:
    build_pdf.render = fake_render  # no Chrome in a test run
    cases = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for case in cases:
        needs_tmp = case.__code__.co_argcount == 1
        with tempfile.TemporaryDirectory() as raw:
            try:
                case(Path(raw)) if needs_tmp else case()
            except Exception as exc:  # noqa: BLE001 - a report, not a traceback per case
                failures += 1
                print(f"FAIL {case.__name__}: {type(exc).__name__}: {exc}")
                import traceback

                traceback.print_exc()
                continue
        print(f"ok   {case.__name__}")
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
