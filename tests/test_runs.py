"""runs.py: runs started, followed and cancelled. No LLM: `stream` is a fake
that behaves like stream_task."""

from __future__ import annotations

import threading
import time

import pytest
from openhands.sdk import Message, TextContent

from certo.api import RunOptions, UsageError
from certo.cancel import RunCancelled
from certo.config import Config
from certo.runner import NOTICE_NAME, CompletionContract, TaskOutcome
from certo.runs import RunManager, UnknownRun


def _cfg(tmp_path, **overrides) -> Config:
    base = {
        "model": "openai/gpt-4o",
        "api_key": "key",
        "base_url": None,
        "workspace": str(tmp_path / "ws"),
        "projects_dir": str(tmp_path / "projects"),
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


def _outcome(state="verified") -> TaskOutcome:
    contract = CompletionContract(
        goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
    )
    return TaskOutcome(verification_state=state, completion_contract=contract)


def _wait(manager, run_id, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = manager.status(run_id)
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the run didn't end")


def test_a_run_starts_at_once_and_ends_with_its_result(tmp_path):
    seen = {}

    def stream(task, *, on_message, cancel, save_state, **kwargs):
        seen.update(save_state=save_state, cfg=kwargs["cfg"])
        on_message(Message(role="assistant", content=[TextContent(text="working")]))
        on_message(
            Message(role="assistant", content=[TextContent(text="checked")], name=NOTICE_NAME)
        )
        return _outcome()

    manager = RunManager(load=lambda: _cfg(tmp_path), stream=stream)
    run = manager.start("do it", RunOptions(project="demo"))
    status = _wait(manager, run.id)

    assert status["state"] == "finished"
    assert status["verdict"] == "verified"
    assert status["result"]["task"] == "do it"
    assert status["project"] == "demo"
    assert seen["save_state"] is True
    events = manager.events(run.id)
    assert [(e["kind"], e["text"]) for e in events["events"]] == [
        ("message", "working"),
        ("notice", "checked"),
    ]
    assert events["next"] == 2
    assert manager.events(run.id, since=2)["events"] == []


def test_cancel_stops_a_run_and_keeps_why(tmp_path):
    started = threading.Event()

    def stream(task, *, cancel, **_kwargs):
        started.set()
        cancel.wait(5)
        raise RunCancelled()

    manager = RunManager(load=lambda: _cfg(tmp_path), stream=stream)
    run = manager.start("do it", RunOptions())
    started.wait(5)
    manager.cancel(run.id)
    status = _wait(manager, run.id)

    assert status["state"] == "cancelled"
    assert status["verdict"] is None
    assert status["result"]["error"] == "cancelled"


def test_one_run_per_folder_at_a_time(tmp_path):
    release = threading.Event()

    def stream(task, **_kwargs):
        release.wait(5)
        return _outcome()

    manager = RunManager(load=lambda: _cfg(tmp_path), stream=stream)
    first = manager.start("one", RunOptions(project="demo"))
    with pytest.raises(UsageError, match="still working"):
        manager.start("two", RunOptions(project="demo"))
    other = manager.start("three", RunOptions(project="other"))
    release.set()
    _wait(manager, first.id)
    _wait(manager, other.id)
    again = manager.start("four", RunOptions(project="demo"))
    _wait(manager, again.id)


def test_an_error_ends_the_run_with_the_error(tmp_path):
    def stream(task, **_kwargs):
        raise RuntimeError("provider down")

    manager = RunManager(load=lambda: _cfg(tmp_path), stream=stream)
    run = manager.start("do it", RunOptions())
    status = _wait(manager, run.id)

    assert status["state"] == "error"
    assert status["result"]["error"] == "provider down"
    # The folder is free again.
    _wait(manager, manager.start("again", RunOptions()).id)


def test_a_wrong_setting_is_refused_before_anything_runs(tmp_path):
    calls = []
    manager = RunManager(
        load=lambda: _cfg(tmp_path), stream=lambda *a, **k: calls.append(a) or _outcome()
    )
    with pytest.raises(UsageError):
        manager.start("do it", RunOptions(agents_md="x"))
    assert calls == []
    assert manager.list() == []


def test_an_unknown_run_id_is_refused(tmp_path):
    manager = RunManager(load=lambda: _cfg(tmp_path))
    with pytest.raises(UnknownRun):
        manager.status("nope")


def test_each_run_is_added_to_the_projects_runs_md(tmp_path):
    manager = RunManager(load=lambda: _cfg(tmp_path), stream=lambda task, **_k: _outcome())
    run = manager.start("do it", RunOptions(project="demo"))
    _wait(manager, run.id)
    runs_md = (tmp_path / "projects" / "demo" / ".certo" / "RUNS.md").read_text()
    assert "do it" in runs_md
    assert "verified" in runs_md
    # Linked to its report, which is in the folder.
    link = runs_md.split("- Report: [", 1)[1].split("]", 1)[0]
    report = (tmp_path / "projects" / "demo" / ".certo" / link).read_text()
    assert report.startswith("# Run report · verified")
