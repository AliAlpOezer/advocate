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

import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.messages import AIMessage  # noqa: E402

import advocate.apply.stages as stages  # noqa: E402
import advocate.render.build_pdf as build_pdf  # noqa: E402
from advocate.apply.documents import body_of, normalise_body, splice_body  # noqa: E402
from advocate.apply.graph import build_graph  # noqa: E402
from advocate.apply.providers import default_chain  # noqa: E402
from advocate.apply.stages import (  # noqa: E402
    CLAIMS_USED,
    CV,
    DRAFTING_STAGES,
    LETTER,
    STRATEGY,
    TEMPLATE_SLUG,
    Application,
    cv_problems,
)

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


@pytest.fixture
def tmp() -> Iterator[Path]:
    """A scratch directory per test.

    Added 2026-08-08. Fourteen of the eighteen tests in this file take `tmp` and
    nothing ever defined it, so they have errored at setup since they were
    written - `fixture 'tmp' not found`, which pytest reports as an ERROR rather
    than a failure and which a summary line reads straight past. "18 Python tests
    pass" in STATUS.md was a count of collected tests; four of them ran.

    That is the same shape as the two silent-success traps already recorded here:
    the check did not fail, it stopped being performed, and the report agreed with
    it. Worth remembering that it hid the TEMPLATE_SLUG drift's blast radius as
    well - the tests written to catch that never executed either.
    """
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


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
        self.preferred: list[str | None] = []  # the route asked for, per turn
        self.turns = 0

    def invoke(self, messages, tools=None, prefer=None):
        self.turns += 1
        self.calls.append(sorted(t.name for t in (tools or [])))
        self.preferred.append(prefer)
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


def test_template_slug_is_the_folder_the_driver_actually_copies_from() -> None:
    """Pinned to a literal, deliberately, because every other test derives from it.

    `make_repo` builds its template dir at `applications/<TEMPLATE_SLUG>/`, so the
    suite agrees with this constant whatever it says and cannot see it drift. It
    did drift: verify.ts moved to `_template` on 2026-08-07, this side stayed on
    `SSI_Schaefer_Bewerbung` until 2026-08-08, and in between every new scaffold
    was compared against a real sent application - which exists and differs, so
    `cv_problems()` came back empty and `draft_cv` skipped itself over an
    untouched template. The literal is the only thing a fixture cannot fake.
    """
    assert TEMPLATE_SLUG == "_template"


def test_a_missing_template_fails_loudly_rather_than_passing_the_check(tmp: Path) -> None:
    """A guard that cannot check must not report success.

    `template()` used to return "" for a missing file, which made the
    byte-identity comparison silently false - "no problem" at exactly the moment
    it had stopped being able to tell.
    """
    app = make_repo(tmp)
    (app.template_dir / CV).unlink()

    try:
        problems = cv_problems(app)
    except SystemExit as exc:
        assert "TEMPLATE_SLUG" in str(exc)
    else:
        raise AssertionError(
            f"a missing template reported {problems!r} instead of failing - the byte-identity "
            f"guard was blind and said nothing was wrong"
        )


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


def test_a_revision_redrafts_instead_of_skipping_finished_stages(tmp: Path) -> None:
    """The resume shortcut is right for a retry and catastrophic for a revision.

    A stage is skipped when its `problems()` are empty, which is what makes a
    crashed run resume where it stopped. But a draft that reached Alp has no
    problems by definition - passing every mechanical check is how it got in
    front of him - so applying the same rule to a redraft would skip all four
    stages, re-render the document he rejected, and report a successful revision.
    """
    app = make_repo(tmp)
    run(app, StubChat(script_for(app.slug)))  # first draft: everything now on disk

    revised = replace(app, revision_reason="Zu generisch, der Bezug zur Stelle fehlt.")
    chat = StubChat(script_for(app.slug))
    final = run(revised, chat)

    assert not final.get("failed"), final.get("failed")
    assert not any(s["skipped"] for s in final["stages"]), [s["stage"] for s in final["stages"] if s["skipped"]]
    assert final["turns"] == 4, final["turns"]


def test_a_revision_that_writes_nothing_fails_rather_than_reporting_success(tmp: Path) -> None:
    """The silent-success shape, in the one place the file checks cannot see it.

    Every check passes before the model does anything, so "no problems" is not
    evidence of work here. A model that reads the brief, agrees, and writes
    nothing has to fail the stage - otherwise the pipeline re-renders the
    rejected document and hands Alp back exactly what he sent away.
    """
    app = make_repo(tmp)
    run(app, StubChat(script_for(app.slug)))

    revised = replace(app, revision_reason="Der zweite Absatz stimmt so nicht.")
    chat = StubChat(["Ich habe das geprueft, die Unterlagen passen bereits."] * 10)
    final = run(revised, chat)

    assert final.get("failed") == "analyse", final.get("failed")
    record = stage(final, "analyse")
    assert not record["ok"]
    assert record["problems"], "the stage must say why it failed"
    assert "redraft" in record["problems"][0]
    # It pushed back rather than accepting the first refusal.
    assert record["nudges"] > 0


def test_the_revision_brief_leads_every_stage_task(tmp: Path) -> None:
    app = replace(make_repo(tmp), revision_reason="Bitte den Munich-Bezug staerker machen.")
    for stage_def in DRAFTING_STAGES:
        task = stage_def.task_for(app)
        assert task.startswith("=== THIS IS A REDRAFT ==="), stage_def.name
        assert "Munich-Bezug" in task, stage_def.name
    # And no brief at all when there is nothing to say - an empty redraft banner
    # would tell a first draft it is correcting something that never happened.
    first = replace(app, revision_reason="")
    assert not DRAFTING_STAGES[0].task_for(first).startswith("===")


def test_the_paid_tier_is_reachable_only_by_asking_for_it() -> None:
    """Escalation is opt-in, never a fallback, and never fatal when unavailable."""
    saved = os.environ.get("ANTHROPIC_API_KEY")
    try:
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"

        # A normal draft never touches it, however the free rungs fail.
        assert all(t.provider != "anthropic" for t in default_chain())

        # A revision puts it on top, and keeps the free rungs underneath so an
        # exhausted key degrades the draft instead of losing it.
        escalated = default_chain(escalate=1)
        assert escalated[0].provider == "anthropic"
        assert escalated[0].model == "claude-opus-5"
        assert [t.provider for t in escalated[1:]] == ["openrouter", "openrouter"]

        # No key: still a chain, just not the one asked for.
        del os.environ["ANTHROPIC_API_KEY"]
        assert all(t.provider != "anthropic" for t in default_chain(escalate=1))
    finally:
        if saved is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_a_stage_route_leads_the_free_chain_but_never_displaces_an_escalation() -> None:
    """`claims` runs on its own model; the ordering rules around it are the point.

    The stage preference exists because tier 1 cannot serve that request at all
    (0 usable turns in 6 replays, 2026-08-08). Two things must stay true anyway:
    a revision Alp paid for still starts on the paid rung, and the ordinary free
    chain stays underneath so a rate-limited preference degrades rather than
    fails.
    """
    from advocate.apply.providers import ChainedChat, default_chain

    saved = os.environ.get("ANTHROPIC_API_KEY")
    try:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        chat = ChainedChat(default_chain())

        # No preference: the chain is untouched, so every other stage is unaffected.
        assert [t.model for t in chat._chain_for(None)] == [t.model for t in chat.tiers]

        # With one: it leads, and the standard rungs remain as fallback.
        chain = chat._chain_for("poolside/laguna-s-2.1:free")
        assert chain[0].model == "poolside/laguna-s-2.1:free"
        assert [t.model for t in chain[1:]] == [t.model for t in chat.tiers]

        # A preference that is already in the chain is not duplicated - it leads
        # once, rather than being retried twice before the fallback is reached.
        already = chat._chain_for(chat.tiers[1].model)
        assert [t.model for t in already].count(chat.tiers[1].model) == 1

        # An escalation outranks it. Alp tapped Revise and is paying for that.
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        escalated = ChainedChat(default_chain(escalate=1))._chain_for("poolside/laguna-s-2.1:free")
        assert escalated[0].provider == "anthropic"
        assert escalated[1].model == "poolside/laguna-s-2.1:free"
    finally:
        if saved is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_the_stage_route_actually_reaches_the_model_call(tmp: Path) -> None:
    """`Stage.model` is only worth anything if the chain is told about it.

    Pinned end to end rather than on the dataclass, because the failure this
    guards against is the field being set and silently never forwarded - which
    looks exactly like the fix working right up until the run fails the same way
    it did before.
    """
    app = make_repo(tmp)
    chat = StubChat(script_for(app.slug))
    run(app, chat)

    # One turn per stage, in pipeline order, so the fourth is claims.
    assert chat.preferred == [None, None, None, stages.CLAIMS_MODEL], chat.preferred


def test_only_the_claims_stage_carries_a_route_of_its_own() -> None:
    """The stages that already work keep the model whose German has been read.

    Pinned as a literal rather than derived from the tuple, for the same reason
    the TEMPLATE_SLUG test is: a check computed from the thing under test agrees
    with it however it drifts.
    """
    by_name = {s.name: s for s in DRAFTING_STAGES}
    assert by_name["claims"].model == stages.CLAIMS_MODEL
    assert [n for n, s in by_name.items() if s.model] == ["claims"]


def test_the_corpus_is_marked_as_a_cache_breakpoint_for_anthropic_only() -> None:
    """The 85 KB corpus is re-sent every turn; on the paid rung that has to cache.

    Caching is a prefix match, so this also checks the volatile half stays
    *after* the breakpoint - a task message pulled into the cached block would
    make every application a fresh cache entry and cost more than it saves.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from advocate.apply.providers import _cacheable

    messages = [SystemMessage(content="CORPUS"), HumanMessage(content="the task")]
    marked = _cacheable(messages)

    assert marked[0].content == [
        {"type": "text", "text": "CORPUS", "cache_control": {"type": "ephemeral"}}
    ]
    assert marked[1].content == "the task", "the volatile turn must stay unmarked"
    assert messages[0].content == "CORPUS", "the caller's messages must not be mutated"


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
