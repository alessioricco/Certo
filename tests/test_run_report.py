"""run_report.py: a run's report page, from its JSON result. No LLM:
outcomes are constructed (test_result.py's)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from test_result import _outcome

from certo.escalation import FileChanges
from certo.result import run_result
from certo.run_report import render_report, report_relpath, write_report
from certo.runner import CompletionContract

_STARTED = datetime(2026, 11, 3, 16, 19, 5, tzinfo=UTC)


def _report(outcome=None, **kwargs) -> str:
    result = run_result(outcome, task="Write slug.py\nwith a test", workspace="/p", **kwargs)
    return render_report(result, _STARTED)


def test_the_report_says_why_the_verdict_with_the_failing_checks_output():
    text = _report(_outcome(tool_call_reminders=2), project="demo")

    assert text.startswith("# Run report · retry_exhausted\n")
    assert "- Started: 2026-11-03 16:19 UTC" in text
    assert "- Project: demo" in text
    assert "> Write slug.py\n> with a test" in text
    assert "- Not checked: pytest failed" in text
    assert "- Check `pytest` failed: 1 failed" in text
    assert "- Certo sent the agent back to fix failing checks 2 time(s)" in text
    assert "| pytest | failed | `python -m pytest` | 1 failed |" in text
    # The end of a failing check's output, in a code block.
    assert "End of `pytest`'s output:\n\n```text\n" in text
    assert "FAILED test_a\n```" in text
    assert "| a.py | yes | yes | found |" in text
    assert "| `anthropic/claude-haiku-5-5` | default | 100 / 20 | $0.0123 |" in text
    assert "2 tool-call reminder(s)" in text


def test_a_run_that_passed_says_so_and_lists_its_files():
    changes = FileChanges(created=("slug.py", "test_slug.py"), modified=("README.md",))
    text = _report(
        _outcome(
            verification_state="verified",
            retries_used=0,
            checks=(),
            files_changed=changes,
            completion_contract=CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        )
    )

    assert "- Every check Certo ran passed." in text
    assert "Certo ran no check." in text
    assert "**Created** (2):\n- `slug.py`\n- `test_slug.py`" in text
    assert "**Modified** (1):\n- `README.md`" in text
    assert "Deleted" not in text


def test_a_run_that_stopped_early_says_why_and_what_isnt_known():
    text = _report(None, error="interrupted")

    assert text.startswith("# Run report · no verdict\n")
    assert "- Stopped: interrupted" in text
    assert "Not known: the run stopped before Certo compared the files." in text
    assert "Not known: the run stopped before it used a model." in text


def test_milestones_are_listed_with_their_verdicts():
    milestones = [
        {"number": 1, "title": "entries", "verdict": "verified"},
        {"number": 2, "title": "totals", "verdict": None},
    ]
    text = _report(_outcome(), milestones=milestones)

    assert "| 1. entries | verified |" in text
    assert "| 2. totals | not started |" in text


def test_a_pipe_or_a_new_line_in_a_cell_does_not_break_the_table():
    result = run_result(_outcome(), task="t", workspace="/p")
    result["checks"][0]["summary"] = "a | b\nc"

    assert "| a \\| b c |" in render_report(result, _STARTED)


def test_the_report_goes_under_certo_reports_named_by_the_start_time(tmp_path):
    result = run_result(_outcome(), task="t", workspace=str(tmp_path))

    path = write_report(str(tmp_path), result, _STARTED)

    assert report_relpath(_STARTED) == "reports/2026-11-03T16-19-05Z.md"
    assert path == str(tmp_path / ".certo" / "reports" / "2026-11-03T16-19-05Z.md")
    assert (
        (tmp_path / ".certo" / "reports" / "2026-11-03T16-19-05Z.md")
        .read_text(encoding="utf-8")
        .startswith("# Run report · retry_exhausted")
    )
    # .certo/ ignores itself, as for the run state.
    assert (tmp_path / ".certo" / ".gitignore").exists()


def test_only_the_last_lines_of_a_long_output_are_shown():
    result = run_result(_outcome(), task="t", workspace="/p")
    result["checks"][0]["output_tail"] = "\n".join(f"line {i}" for i in range(100))

    text = render_report(result, _STARTED)

    assert "line 60\n" in text
    assert "line 59\n" not in text


def test_an_escalation_shows_each_rung_and_how_the_model_was_chosen():
    result = run_result(_outcome(), task="t", workspace="/p")
    result["rungs"] = [
        {
            "rung": 1,
            "name": "local",
            "model": "ollama/qwen3.8:27b",
            "verdict": None,
            "failure": "provider error",
            "fix_attempts": 0,
            "duration_seconds": 61.0,
            "cost": 0.0,
            "cost_known": True,
            "final": False,
        },
        {
            "rung": 2,
            "name": "haiku",
            "model": "anthropic/claude-haiku-5-5",
            "verdict": "verified",
            "failure": None,
            "fix_attempts": 1,
            "duration_seconds": 250.6,
            "cost": 0.05,
            "cost_known": True,
            "final": True,
        },
    ]
    result["model_decisions"] = [
        {"kind": "ladder", "chosen": "local", "reason": "the first rung"},
    ]

    text = render_report(result, _STARTED)

    assert (
        "| 1 | local (`ollama/qwen3.8:27b`) | provider error | 0 | 1m 01s | $0.0000 | - |" in text
    )
    assert (
        "| 2 | haiku (`anthropic/claude-haiku-5-5`) | verified | 1 | 4m 11s | $0.0500 | yes |"
        in text
    )
    assert "- Chose `local` (ladder): the first rung" in text


def test_a_checks_command_is_shown_inside_the_project(tmp_path):
    result = run_result(_outcome(), task="t", workspace=str(tmp_path))
    result["checks"][0]["command"] = f"{tmp_path}{os.sep}.venv/bin/python -m pytest -q"

    assert "| `.venv/bin/python -m pytest -q` |" in render_report(result, _STARTED)


def test_the_report_lists_the_skills_the_run_had():
    text = _report(_outcome(skills_used=("testing-and-verification", "pytest-conventions")))
    assert "## Skills\n\ntesting-and-verification, pytest-conventions\n" in text

    assert "## Skills\n\nThe run had no skills.\n" in _report(_outcome())


def test_a_milestone_runs_report_lists_each_milestones_skills():
    milestones = [
        {"number": 1, "title": "Set up", "verdict": "verified", "skills": ["repository-discovery"]},
        {"number": 2, "title": "Play", "verdict": "verified", "skills": []},
        {"number": 3, "title": "Ship", "verdict": None, "skills": None},  # not run
    ]
    text = _report(_outcome(skills_used=("x",)), milestones=milestones)

    assert "## Skills\n\n- Milestone 1: repository-discovery\n- Milestone 2: none\n\n" in text
    assert "Milestone 3:" not in text.split("## Skills")[1].split("##")[0]
