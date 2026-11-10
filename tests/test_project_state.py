"""project_state.py: the `.certo/` folder behind `certo --resume`."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from certo import project_state
from certo.project_state import RunRecord


def _record(**overrides) -> RunRecord:
    values = {
        "task": "Build a Wordle game",
        "conversation_id": "a" * 32,
        "model": "ollama/qwen3-coder:30b",
        "execution": "local",
        "started_at": "2026-10-16T10:00:00+00:00",
        "updated_at": "2026-10-16T10:00:00+00:00",
    }
    values.update(overrides)
    return RunRecord(**values)


def _check(name="pytest", status="failed", output="", command="pytest -q"):
    return SimpleNamespace(name=name, status=status, command=command, output=output)


def test_save_and_load_round_trip(tmp_path):
    record = _record(
        status="finished",
        verdict="retry_exhausted",
        checks=project_state.checks_from_outcomes([_check(output="E   assert 2 == 3")]),
    )

    project_state.save_record(str(tmp_path), record)
    loaded = project_state.load_record(str(tmp_path))

    assert loaded == record
    assert (tmp_path / ".certo" / "run.json").is_file()
    assert (tmp_path / ".certo" / "STATUS.md").is_file()


def test_load_record_is_none_without_state_or_with_a_broken_file(tmp_path):
    assert project_state.load_record(str(tmp_path)) is None
    (tmp_path / ".certo").mkdir()
    (tmp_path / ".certo" / "run.json").write_text("{not json")
    assert project_state.load_record(str(tmp_path)) is None


def test_load_record_ignores_fields_it_does_not_know(tmp_path):
    project_state.save_record(str(tmp_path), _record())
    path = tmp_path / ".certo" / "run.json"
    data = json.loads(path.read_text())
    data["added_by_a_later_version"] = 1
    path.write_text(json.dumps(data))

    assert project_state.load_record(str(tmp_path)).task == "Build a Wordle game"


def test_state_folder_ignores_itself_in_git(tmp_path):
    git = pytest.importorskip("shutil").which("git")
    if git is None:
        pytest.skip("git not installed")
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    project_state.save_record(str(tmp_path), _record())

    status = subprocess.run(
        [git, "-C", str(tmp_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert status.stdout == ""


def test_status_md_names_the_model_with_its_reasoning_effort():
    record = _record(status="finished", verdict="verified")
    record.model = "ollama/qwen3.8:27b"
    record.reasoning_effort = "high"

    assert "- Model: ollama/qwen3.8:27b (effort high)" in project_state.render_status(record)


def test_status_md_shows_the_verdict_failing_checks_and_their_output(tmp_path):
    record = _record(
        status="finished",
        verdict="no_progress",
        retries_used=1,
        checks=project_state.checks_from_outcomes(
            [
                _check(output="tests/test_game.py::test_score FAILED\nE   assert 2 == 3"),
                _check(name="ruff", status="passed", output="All checks passed!"),
            ]
        ),
        limitations=["mypy is configured but not installed"],
    )

    text = project_state.render_status(record)

    assert "finished, verdict `no_progress`" in text
    assert "Build a Wordle game" in text
    assert "- Model: " in text and "(effort default)" in text
    assert "- `failed` pytest (`pytest -q`)" in text
    assert "E   assert 2 == 3" in text
    # Output is kept only for checks that didn't pass.
    assert "All checks passed!" not in text
    assert "mypy is configured but not installed" in text


def test_only_the_end_of_a_long_output_is_kept():
    long_output = "x" * 10_000 + "THE ERROR"
    [record] = project_state.checks_from_outcomes([_check(output=long_output)])
    assert record.output_tail.endswith("THE ERROR")
    assert len(record.output_tail) == 2000


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("running", "stopped before Certo could record"),
        ("interrupted", "interrupted"),
        ("error", "stopped with an error: boom"),
    ],
)
def test_status_md_says_how_an_unfinished_run_ended(status, expected):
    assert expected in project_state.render_status(_record(status=status, error="boom"))


def test_resume_message_with_context_skips_the_preamble_about_files_only():
    record = _record(status="interrupted")
    with_context = project_state.resume_message(record, "use port 8080", has_context=True)
    without = project_state.resume_message(record, None, has_context=False)

    assert "being resumed" in with_context
    assert "use port 8080" in with_context
    assert "conversation isn't available" in without
    # Without the conversation, the message must carry the task itself.
    assert "Build a Wordle game" in without


def test_drop_other_conversations_keeps_only_the_named_one(tmp_path):
    root = tmp_path / ".certo" / "conversations"
    (root / "old").mkdir(parents=True)
    (root / "keep").mkdir()

    project_state.drop_other_conversations(str(tmp_path), keep="keep")

    assert [p.name for p in root.iterdir()] == ["keep"]


def test_status_says_a_run_was_stopped_at_a_limit():
    record = RunRecord(
        task="t",
        conversation_id="a" * 32,
        model="m",
        execution="local",
        started_at="s",
        updated_at="u",
        status="finished",
        verdict="verified",
        cut_short=True,
    )
    text = project_state.render_status(record)
    assert "stopped at a limit before the agent said it was done, verdict `verified`" in text
    assert RunRecord.from_dict(json.loads(json.dumps(record.__dict__ | {"checks": []}))).cut_short
