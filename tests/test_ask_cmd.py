"""docs_index.py and ask_cmd.py: `certo ask`. No LLM: the model's replies
are given by a fake `complete`."""

from __future__ import annotations

import os

from certo.ask_cmd import MAX_CONTEXT_CHARS, ask, ask_main, pick_sections, render
from certo.docs_index import (
    keyword_hits,
    names_in,
    slug,
    split_sections,
    table_of_contents,
)
from certo.docs_source import Docs, DocsUnavailable, checkout_docs, user_pages

_PAGES = [
    (
        "guides/resume-a-run.md",
        "# Resume an interrupted run\n\nIntro.\n\n## Continue\n\nRun `certo --resume`.\n\n"
        "```text\n## not a heading\n```\n\n## Continue\n\nAgain.\n",
    ),
    (
        "reference/configuration.md",
        "# Configuration\n\n## Limits\n\n| `CERTO_MAX_TASK_COST` | empty | A cost limit. |\n",
    ),
]


def _sections():
    return split_sections(_PAGES)


def test_pages_split_at_headings_outside_code_with_githubs_anchors():
    sections = _sections()
    assert [(s.id, s.page, s.level, s.title, s.anchor) for s in sections] == [
        (
            "S1",
            "guides/resume-a-run.md",
            1,
            "Resume an interrupted run",
            "resume-an-interrupted-run",
        ),
        ("S2", "guides/resume-a-run.md", 2, "Continue", "continue"),
        ("S3", "guides/resume-a-run.md", 2, "Continue", "continue-1"),
        ("S4", "reference/configuration.md", 1, "Configuration", "configuration"),
        ("S5", "reference/configuration.md", 2, "Limits", "limits"),
    ]
    assert "## not a heading" in sections[1].text
    assert slug("The `.certo` folder") == "the-certo-folder"


def test_the_table_of_contents_lists_pages_and_their_sections_by_id():
    assert table_of_contents(_sections()) == (
        "guides/resume-a-run.md: Resume an interrupted run (S1)\n"
        "  S2 Continue\n  S3 Continue\n"
        "reference/configuration.md: Configuration (S4)\n  S5 Limits"
    )


def test_exact_names_in_a_question_find_their_sections():
    assert names_in("What is CERTO_MAX_TASK_COST and --max-time? and no_progress") == [
        "CERTO_MAX_TASK_COST",
        "--max-time",
        "no_progress",
    ]
    hits = keyword_hits("How do I set CERTO_MAX_TASK_COST?", _sections())
    assert [s.id for s in hits] == ["S5"]
    assert keyword_hits("how do I stop a run?", _sections()) == []


def _complete(*replies):
    prompts, answers = [], list(replies)

    def complete(prompt):
        prompts.append(prompt)
        return answers.pop(0), 0.001

    return complete, prompts


def test_an_answer_cites_its_sections_and_shows_them_as_links(tmp_path):
    complete, prompts = _complete("S2 S5", "Run `certo --resume` [S2]. A limit too [S5, S9].")
    answer = ask("How do I continue a run?", _sections(), complete)

    assert [s.id for s in answer.used] == ["S2", "S5"]
    assert "S2 Continue" in prompts[0] and "How do I continue a run?" in prompts[0]
    assert "[S2] guides/resume-a-run.md\n## Continue" in prompts[1]
    assert answer.covered and [s.id for s in answer.cited] == ["S2", "S5"]
    assert answer.unknown_citations == ["S9"]
    assert round(answer.cost, 3) == 0.002
    docs = Docs(str(tmp_path), "cache", "0.2.4")
    lines = "\n".join(render(answer, docs))
    assert lines.startswith("Run `certo --resume` [1]. A limit too [2].")
    assert "[1] guides/resume-a-run.md › Continue" in lines
    assert (
        "https://github.com/alessioricco/certo/blob/v0.2.4/docs/guides/resume-a-run.md#continue"
        in lines
    )


def test_a_question_the_docs_dont_cover_says_so_with_the_closest_pages(tmp_path):
    complete, _ = _complete("S2", "NOT COVERED")
    answer = ask("How do I deploy on Kubernetes?", _sections(), complete)
    assert not answer.covered and answer.text == ""
    lines = render(answer, Docs(str(tmp_path), "checkout", "0.2.4"))
    assert lines[0] == "The docs don't cover this."
    assert lines[-1].endswith(os.path.join("guides", "resume-a-run.md"))


def test_no_section_picked_and_no_name_to_search_needs_no_second_call():
    complete, prompts = _complete("NONE")
    answer = ask("What's the weather?", _sections(), complete)
    assert not answer.covered and answer.used == [] and len(prompts) == 1


def test_a_named_setting_is_added_even_when_the_model_misses_it():
    picked = pick_sections("Set CERTO_MAX_TASK_COST?", _sections(), "S2")
    assert [s.id for s in picked] == ["S2", "S5"]


def test_an_answer_with_no_citation_comes_with_a_warning(tmp_path):
    complete, _ = _complete("S2", "Use --resume.")
    answer = ask("How do I continue?", _sections(), complete)
    assert answer.uncited
    lines = "\n".join(render(answer, Docs(str(tmp_path), "cache", "0.2.4")))
    assert "names no section of the docs, so it can't be checked" in lines


def test_ask_main_prints_the_answer(tmp_path, capsys):
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True)
    for page, text in _PAGES:
        (docs / page).parent.mkdir(parents=True, exist_ok=True)
        (docs / page).write_text(text)
    complete, _ = _complete("S2", "Run `certo --resume` [S2].")
    assert (
        ask_main(
            ["how", "do", "I", "continue?"],
            complete=complete,
            docs=Docs(str(docs), "checkout", "0.2.4"),
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Run `certo --resume` [1]." in out and "Sources:" in out
    assert "from 1 section(s)" in out


def test_ask_main_without_docs_is_an_error(monkeypatch, capsys):
    def no_docs(version):
        raise DocsUnavailable("Couldn't download Certo's docs.")

    monkeypatch.setattr("certo.ask_cmd.find_docs", no_docs)
    assert ask_main(["anything?"], complete=lambda p: ("", 0.0)) == 1
    assert "Couldn't download" in capsys.readouterr().err


def test_the_real_docs_fit_a_small_context_window():
    # Both calls must fit a 32K local window (TODO, "Ask Certo about
    # Certo"): the table of contents, and the sections sent to answer.
    sections = split_sections(user_pages(checkout_docs()))
    assert len(table_of_contents(sections)) < 24_000
    assert all(len(s.short_text) <= MAX_CONTEXT_CHARS for s in sections)
    assert len({(s.page, s.anchor) for s in sections}) == len(sections)


def test_a_long_section_keeps_its_start_and_the_lines_the_question_is_about():
    from certo.docs_index import Section, excerpt

    rows = [f"| `--flag-{n}` | off | Does thing number {n}. |" for n in range(400)]
    rows[350] = "| `--verbose` | off | Print the whole system prompt. |"
    text = "## `certo`\n\nIntro line.\n\n" + "\n".join(rows)
    section = Section("S1", "reference/commands.md", 2, "`certo`", "certo", text)
    cut = excerpt(section, "How do I see the full system prompt?", limit=2000)
    assert len(cut) <= 2000
    assert cut.startswith("## `certo`\n\nIntro line.")
    assert "| `--verbose` | off | Print the whole system prompt. |" in cut
    assert "[…]" in cut


def test_a_question_without_exact_names_adds_the_section_sharing_most_words():
    from certo.docs_index import split_sections, word_hits

    sections = split_sections(
        [
            ("guides/a.md", "# A\n\n## Other\n\nSomething else entirely.\n"),
            (
                "reference/configuration.md",
                "# Configuration\n\n## Limits and verification\n\n"
                "| `CERTO_VERBOSE` | Print the full system prompt the agent gets. |\n",
            ),
        ]
    )
    assert [s.title for s in word_hits("How do I see the full system prompt?", sections)] == [
        "Limits and verification"
    ]
    assert word_hits("What is CERTO_VERBOSE?", sections) == []  # names go by keyword_hits


def test_search_ranks_exact_names_then_heading_words():
    from certo.docs_index import search

    assert [s.id for s in search("CERTO_MAX_TASK_COST", _sections())] == ["S5"]
    assert search("continue", _sections())[0].title == "Continue"
    assert search("zzzz qqqq", _sections()) == []


# --mine: the user's own setup goes with the question, keys hidden.

_FAKE_KEY = "sk-ant-" + "x" * 30


def _mine(tmp_path, monkeypatch):
    from certo.ask_cmd import gather_mine

    project = tmp_path / "project"
    (project / ".certo" / "reports").mkdir(parents=True)
    (project / "MODEL_DECISIONS.md").write_text(
        "# Model Decisions\n\nTask profile: `architecture`\n\nChosen: **claude-opus**\n"
    )
    (project / ".certo" / "reports" / "2026-11-17T08-00-00Z.md").write_text("old run\n")
    (project / ".certo" / "reports" / "2026-11-18T08-00-00Z.md").write_text(
        f"Verdict: verified\nA key in an error: {_FAKE_KEY}\n"
    )
    monkeypatch.setenv("CERTO_LLM_API_KEY", "a-settings-secret-value-123")

    def check_text(folder):
        assert folder == str(project)
        return "Settings:\n  CERTO_LLM_MODEL  anthropic/claude-opus\n  leaked a-settings-secret-value-123\n"

    return gather_mine(str(project), check_text=check_text), project


def test_mine_gathers_check_decisions_and_the_last_report_with_keys_hidden(tmp_path, monkeypatch):
    mine, project = _mine(tmp_path, monkeypatch)
    assert [s.id for s in mine] == ["Y1", "Y2", "Y3"]
    assert mine[0].page == "certo check" and "anthropic/claude-opus" in mine[0].text
    assert mine[1].page == str(project / "MODEL_DECISIONS.md")
    assert mine[2].page.endswith("2026-11-18T08-00-00Z.md")
    text = "\n".join(s.text for s in mine)
    assert _FAKE_KEY not in text and "a-settings-secret-value-123" not in text
    assert text.count("[hidden]") == 2


def test_mine_without_runs_sends_only_the_check(tmp_path, monkeypatch):
    from certo.ask_cmd import gather_mine

    mine = gather_mine(str(tmp_path), check_text=lambda folder: "Settings: none")
    assert [(s.id, s.page) for s in mine] == [("Y1", "certo check")]


def test_mine_goes_to_both_calls_and_its_citations_show_the_file(tmp_path, monkeypatch):
    mine, project = _mine(tmp_path, monkeypatch)
    complete, prompts = _complete(
        "S2", "Your profile was architecture [Y2], so Opus was chosen [Y2, S2]."
    )
    answer = ask("Why did my run pick Opus?", _sections(), complete, mine=mine)

    assert "own setup" in prompts[0] and "[Y2] Your project's MODEL_DECISIONS.md" in prompts[0]
    assert "ids such as Y1" in prompts[1] and "Chosen: **claude-opus**" in prompts[1]
    assert [s.id for s in answer.cited] == ["Y2", "S2"] and not answer.unknown_citations
    lines = "\n".join(render(answer, Docs(str(tmp_path), "cache", "0.2.4")))
    assert lines.startswith("Your profile was architecture [1], so Opus was chosen [1, 2].")
    assert f"[1] Yours › Your project's MODEL_DECISIONS.md\n      {project}" in lines
    assert "[2] guides/resume-a-run.md › Continue" in lines


def test_without_mine_the_prompts_say_nothing_of_the_users_setup():
    complete, prompts = _complete("S2", "Run it [S2].")
    ask("How do I continue?", _sections(), complete)
    assert "own setup" not in prompts[0] and "Y1" not in prompts[1]


def test_mine_answers_even_when_no_docs_section_is_picked(tmp_path, monkeypatch):
    mine, _ = _mine(tmp_path, monkeypatch)
    complete, prompts = _complete("NONE", "Opus [Y2].")
    answer = ask("Which model did my run use?", _sections(), complete, mine=mine)
    assert answer.covered and [s.id for s in answer.cited] == ["Y2"] and len(prompts) == 2
    lines = render(
        ask("Unrelated?", _sections(), _complete("NONE", "NOT COVERED")[0], mine=mine),
        Docs(str(tmp_path), "cache", "0.2.4"),
    )
    assert lines == ["The docs don't cover this."]


def test_ask_main_with_mine_says_what_it_sends(tmp_path, monkeypatch, capsys):
    mine, _ = _mine(tmp_path, monkeypatch)
    docs = tmp_path / "docs"
    for page, text in _PAGES:
        (docs / page).parent.mkdir(parents=True, exist_ok=True)
        (docs / page).write_text(text)
    complete, _ = _complete("S2", "Opus [Y2].")
    code = ask_main(
        ["--mine", "why", "Opus?"],
        complete=complete,
        docs=Docs(str(docs), "checkout", "0.2.4"),
        mine=mine,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Also sending, with keys hidden:" in out
    assert "[Y1] Your settings and model files (certo check): certo check" in out


def test_project_without_mine_is_refused(capsys):
    import pytest

    with pytest.raises(SystemExit):
        ask_main(["--project", "demo", "why?"], complete=lambda p: ("", 0.0))
    assert "--project needs --mine" in capsys.readouterr().err


def test_the_check_text_calls_no_model(tmp_path, monkeypatch):
    from certo.ask_cmd import _check_text

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "anthropic/claude-haiku-5-5")
    monkeypatch.setattr(
        "certo.llm_check.check_tool_calling",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("called a model")),
    )
    text = _check_text(str(tmp_path))
    assert "CERTO_LLM_MODEL" in text and "anthropic/claude-haiku-5-5" in text
