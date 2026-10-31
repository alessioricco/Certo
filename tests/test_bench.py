"""`certo bench`: isolated runs, grading, recording, cost cap, resume and
interruption, with a fake model. No API key, no network."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from certo import bench
from certo.bench_config import load_bench_config
from certo.bench_tasks import load_tasks, task_set_version
from certo.model_catalog import ModelCatalogEntry
from certo.run_summary import ModelUsage, RunSummary

TASKS = {t.name: t for t in load_tasks()}

MODELS = """
models:
  - name: local-coder
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
  - name: cloud-a
    model: anthropic/test-model-a
    api_key: sk-a
  - name: cloud-b
    model: openai/test-model-b
    api_key: sk-b
"""


def _bench_file(tmp_path: Path, arms: str, tasks: str = "[temperature-table]", repeats: int = 1):
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(tmp_path, MODELS)
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        f"tasks: {tasks}\nrepeats: {repeats}\narms:\n{arms}"
    )
    return str(path)


ONE_ARM = "  - {name: a, strategy: single, model: cloud-a}\n"
TWO_ARMS = ONE_ARM + "  - {name: b, strategy: single, model: cloud-b}\n"


def _summary(cost: float = 0.25) -> RunSummary:
    return RunSummary(
        duration_seconds=1.0,
        models=(ModelUsage(model="m", prompt_tokens=1000, completion_tokens=50, cost=cost),),
    )


class FakeModel:
    """Stands in for runner.stream_task. `solve` copies the task's reference
    solution into the workspace; `verdicts` is consumed one per run."""

    def __init__(
        self,
        make_venv,
        *,
        solve=True,
        verdicts=("verified",),
        cost=0.25,
        raise_on=(),
        independent=None,
    ):
        self.make_venv = make_venv
        self.independent = independent
        self.solve = solve
        self.verdicts = list(verdicts)
        self.cost = cost
        self.raise_on = raise_on
        self.calls: list[SimpleNamespace] = []

    def __call__(self, task_text, *, cfg, on_message=None):
        self.calls.append(SimpleNamespace(task=task_text, cfg=cfg))
        if on_message is not None:
            on_message(f"working on: {task_text[:20]}")
        call = len(self.calls)
        if call in self.raise_on:
            raise self.raise_on[call]
        workspace = Path(cfg.workspace)
        self.seen_files = sorted(p.name for p in workspace.iterdir())
        task = next(t for t in TASKS.values() if t.prompt == task_text)
        if self.solve:
            shutil.copytree(task.reference_dir, workspace, dirs_exist_ok=True)
        if task.language == "python":
            self.make_venv(workspace)
        verdict = self.verdicts[(call - 1) % len(self.verdicts)]
        return SimpleNamespace(
            verification_state=verdict,
            retries_used=1,
            run_summary=_summary(self.cost),
            independent_tests=self.independent if cfg.independent_tests else None,
        )


def _run(path, out, model, *extra):
    return bench.bench_main(
        ["--config", path, "--out", str(out), "--yes", *extra], stream=model, interactive=False
    )


def _records(out: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((out / "runs").glob("*.json"))]


def test_each_run_keeps_its_conversation_beside_the_records(tmp_path, project_venv):
    model = FakeModel(project_venv)
    out = tmp_path / "out"
    assert _run(_bench_file(tmp_path, ONE_ARM), out, model) == 0

    transcript = json.loads(
        (out / "runs" / "transcripts" / "a__temperature-table__r1.json").read_text()
    )
    assert transcript["run_id"] == "a__temperature-table__r1"
    assert transcript["messages"][0]["text"].startswith("working on: ")
    # When each message arrived, from the start of the run.
    assert len(transcript["seconds"]) == len(transcript["messages"])
    assert transcript["seconds"] == sorted(transcript["seconds"])
    assert all(s >= 0 for s in transcript["seconds"])
    assert transcript["started_at"].endswith("+00:00")
    assert len(_records(out)) == 1  # the transcript is not read as a run record


def test_a_transcript_uses_the_messages_own_json_form(tmp_path):
    from openhands.sdk import Message, TextContent

    message = Message(role="assistant", content=[TextContent(text="done")])
    bench.write_transcript(tmp_path, "r1", [message])

    saved = json.loads((tmp_path / "runs" / "transcripts" / "r1.json").read_text())
    assert saved["messages"] == [message.model_dump(mode="json")]


def test_a_run_is_isolated_graded_and_recorded(tmp_path, project_venv, capsys):
    model = FakeModel(project_venv)
    out = tmp_path / "out"
    assert _run(_bench_file(tmp_path, ONE_ARM), out, model) == 0
    call = model.calls[0]
    assert call.task == TASKS["temperature-table"].prompt
    assert call.cfg.model == "anthropic/test-model-a" and call.cfg.api_key == "sk-a"
    assert model.seen_files == []  # no starter for this task, no task.md, no hidden tests
    (record,) = _records(out)
    assert record["verdict"] == "verified"
    assert record["hidden_tests"]["passed"] is True
    assert (record["fooled"], record["caught"], record["agent_claimed_done"]) == (
        False,
        False,
        True,
    )
    assert (record["tokens_in"], record["tokens_out"], record["cost"]) == (1000, 50, 0.25)
    assert record["retries_used"] == 1
    assert record["tool_call_reminders"] == 0
    assert record["models"] == [
        {"name": "cloud-a", "model": "anthropic/test-model-a", "reasoning_effort": None}
    ]
    snapshot = out / "workspaces" / "a__temperature-table__r1"
    assert (snapshot / "temperature.py").is_file()
    assert not (snapshot / ".venv").exists()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["task_set"]["source"] == "bundled"
    assert "| a | single | cloud-a" in (out / "results.md").read_text()
    assert (out / "results.csv").read_text().startswith("run_id,arm,")
    assert (
        "[1/1] a · temperature-table · r1: verified; hidden tests passed" in capsys.readouterr().out
    )


def test_starter_files_are_in_the_workspace(tmp_path, project_venv):
    model = FakeModel(project_venv)
    _run(_bench_file(tmp_path, ONE_ARM, tasks="[inventory-fix]"), tmp_path / "out", model)
    assert model.seen_files == ["inventory.py", "test_inventory.py"]


def test_fooled_when_certo_says_verified_but_hidden_tests_fail(tmp_path, project_venv):
    model = FakeModel(project_venv, solve=False, verdicts=("verified",))
    _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model)
    (record,) = _records(tmp_path / "out")
    assert record["hidden_tests"]["passed"] is False
    assert record["fooled"] is True and record["caught"] is False


def test_caught_when_the_agent_claimed_done_but_certo_did_not_verify(tmp_path, project_venv):
    model = FakeModel(project_venv, solve=False, verdicts=("retry_exhausted",))
    _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model)
    (record,) = _records(tmp_path / "out")
    assert record["caught"] is True and record["fooled"] is False
    assert record["unconfirmed_pass"] is False


def test_unconfirmed_pass_when_hidden_tests_pass_without_verified(tmp_path, project_venv):
    model = FakeModel(project_venv, solve=True, verdicts=("inconclusive",))
    _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model)
    (record,) = _records(tmp_path / "out")
    assert record["caught"] is True and record["unconfirmed_pass"] is True


def test_no_claim_when_the_run_was_stuck(tmp_path, project_venv):
    model = FakeModel(project_venv, solve=False, verdicts=("stuck",))
    _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model)
    (record,) = _records(tmp_path / "out")
    assert record["agent_claimed_done"] is False and record["caught"] is False


def test_a_crashing_run_is_recorded_and_the_benchmark_goes_on(tmp_path, project_venv):
    model = FakeModel(project_venv, raise_on={1: RuntimeError("provider down")})
    assert _run(_bench_file(tmp_path, TWO_ARMS), tmp_path / "out", model) == 0
    first, second = _records(tmp_path / "out")
    assert first["error"] == "RuntimeError: provider down"
    assert first["verdict"] is None and first["hidden_tests"]["passed"] is False
    # It failed before any model call: nothing to count.
    assert first["tokens_in"] == 0 and first["tokens_out"] == 0
    assert first["cost"] == 0.0 and first["condensations"] == 0
    assert second["error"] is None and second["hidden_tests"]["passed"] is True


def test_a_run_that_fails_after_model_calls_keeps_the_usage_it_used(tmp_path, project_venv):
    # runner.stream_task puts the usage recorded up to the error on the
    # exception it raises (issue #30: a 31-minute run recorded 0 tokens).
    crashed = RuntimeError("provider down")
    crashed.run_summary = RunSummary(
        duration_seconds=1800.0,
        models=(ModelUsage(model="m", prompt_tokens=120_000, completion_tokens=4_000, cost=0.4),),
        condensations=2,
    )
    model = FakeModel(project_venv, raise_on={1: crashed})
    assert _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model) == 0
    (record,) = _records(tmp_path / "out")
    assert record["error"] == "RuntimeError: provider down"
    assert record["verdict"] is None
    assert record["tokens_in"] == 120_000 and record["tokens_out"] == 4_000
    assert record["cost"] == 0.4 and record["cost_known"] is True
    assert record["condensations"] == 2


def test_max_cost_stops_cleanly_and_keeps_results(tmp_path, project_venv, capsys):
    model = FakeModel(project_venv, cost=1.0)
    path = _bench_file(tmp_path, TWO_ARMS, repeats=2)
    assert _run(path, tmp_path / "out", model, "--max-cost", "1.5") == 0
    assert len(_records(tmp_path / "out")) == 2
    assert "Stopped: the recorded cost reached --max-cost $1.50." in capsys.readouterr().out


def test_an_arm_time_budget_reaches_the_run_and_the_plan(tmp_path, project_venv, capsys):
    arms = (
        "  - {name: a, strategy: single, model: cloud-a, max_task_seconds: 3600}\n"
        "  - {name: b, strategy: single, model: cloud-b}\n"
    )
    model = FakeModel(project_venv)
    assert _run(_bench_file(tmp_path, arms), tmp_path / "out", model) == 0
    assert "1 run(s) (time budget 60 min per run)" in capsys.readouterr().out
    assert [c.cfg.max_task_seconds for c in model.calls] == [3600, 1800]


def test_an_independent_tests_arm_records_and_reports_them(tmp_path, project_venv, capsys):
    from certo.independent_tests import IndependentTestsResult

    one = IndependentTestsResult(
        "failed", "1 failed", "m", "FAILED .certo_hidden_tests/test_a.py::test_rule - boom"
    )
    result = IndependentTestsResult(
        "failed", "2 of 3 sets failed", "anthropic/test-model-a", sets=(one, one, one)
    )
    arms = (
        "  - {name: a, strategy: single, model: cloud-a, independent_tests: true}\n"
        "  - {name: b, strategy: single, model: cloud-b}\n"
    )
    out = tmp_path / "out"
    model = FakeModel(project_venv, independent=result)
    assert _run(_bench_file(tmp_path, arms), out, model) == 0
    assert "1 run(s) (independent tests on; their writing isn't in the estimate)" in (
        capsys.readouterr().out
    )
    assert [c.cfg.independent_tests for c in model.calls] == [True, False]
    with_, without = _records(out)
    assert with_["independent_tests"] == {
        "status": "failed",
        "summary": "2 of 3 sets failed",
        "model": "anthropic/test-model-a",
        "sets": [
            {
                "status": "failed",
                "summary": "1 failed",
                "failing": [".certo_hidden_tests/test_a.py::test_rule"],
            }
        ]
        * 3,
    }
    assert without["independent_tests"] is None
    report = (out / "results.md").read_text()
    assert "| Independent tests failed | ...hidden passed | ...fooled |" in report
    assert "| 1/1 (100%) | 1 of 1 | 0 of 0 |" in report
    assert "| - | - | - |" in report
    assert "failed" in (out / "results.csv").read_text().splitlines()[1]


def test_stop_at_stops_starting_runs_and_resume_continues(
    tmp_path, project_venv, capsys, monkeypatch
):
    from datetime import datetime

    # Read when parsing --stop-at, then before each run.
    clock = iter(
        [
            datetime(2026, 10, 25, 23, 0),
            datetime(2026, 10, 25, 23, 30),
            datetime(2026, 10, 26, 7, 10),
        ]
    )
    monkeypatch.setattr(bench, "_local_now", lambda: next(clock))
    path = _bench_file(tmp_path, TWO_ARMS, repeats=2)
    out = tmp_path / "out"
    assert _run(path, out, FakeModel(project_venv), "--stop-at", "07:00") == 0
    printed = capsys.readouterr().out
    assert "No new run starts after 2026-10-26 07:00." in printed
    assert "Stopped: it is past --stop-at 07:00." in printed
    assert "3 run(s) not done. Continue with: certo bench --resume" in printed
    assert [r["run_id"] for r in _records(out)] == ["a__temperature-table__r1"]

    model = FakeModel(project_venv)
    assert _run(path, out, model, "--resume") == 0
    assert len(model.calls) == 3
    assert len(_records(out)) == 4


@pytest.mark.parametrize(
    ("value", "wanted"),
    [("07:00", "2026-10-26 07:00"), ("23:30", "2026-10-25 23:30"), ("22:00", "2026-10-26 22:00")],
)
def test_stop_at_is_the_next_such_time(value, wanted):
    from datetime import datetime

    when = bench.parse_stop_at(value, datetime(2026, 10, 25, 22, 0))
    assert f"{when:%Y-%m-%d %H:%M}" == wanted


@pytest.mark.parametrize("value", ["7", "25:00", "7pm", "07:00:00"])
def test_a_bad_stop_at_is_refused(tmp_path, project_venv, capsys, value):
    path = _bench_file(tmp_path, ONE_ARM)
    assert _run(path, tmp_path / "out", FakeModel(project_venv), "--stop-at", value) == 1
    assert "--stop-at must be a 24-hour time like 07:00" in capsys.readouterr().err


def test_interrupt_keeps_finished_runs_and_resume_continues(tmp_path, project_venv):
    path = _bench_file(tmp_path, TWO_ARMS, repeats=2)
    out = tmp_path / "out"
    model = FakeModel(project_venv, raise_on={2: KeyboardInterrupt()})
    assert _run(path, out, model) == 130
    assert [r["run_id"] for r in _records(out)] == ["a__temperature-table__r1"]

    model = FakeModel(project_venv)
    assert _run(path, out, model, "--resume") == 0
    assert len(model.calls) == 3
    assert len(_records(out)) == 4


def test_resume_refuses_a_different_benchmark(tmp_path, project_venv, capsys):
    out = tmp_path / "out"
    _run(_bench_file(tmp_path, ONE_ARM), out, FakeModel(project_venv))
    changed = _bench_file(tmp_path, TWO_ARMS)
    assert _run(changed, out, FakeModel(project_venv), "--resume") == 1
    assert "different tasks, arms, repeats or models" in capsys.readouterr().err


def test_an_existing_results_folder_is_not_overwritten(tmp_path, project_venv, capsys):
    out = tmp_path / "out"
    path = _bench_file(tmp_path, ONE_ARM)
    _run(path, out, FakeModel(project_venv))
    model = FakeModel(project_venv)
    assert _run(path, out, model) == 1
    assert model.calls == []
    assert "already has benchmark results" in capsys.readouterr().err


def test_without_a_terminal_it_needs_yes(tmp_path, project_venv, capsys):
    model = FakeModel(project_venv)
    path = _bench_file(tmp_path, ONE_ARM)
    code = bench.bench_main(
        ["--config", path, "--out", str(tmp_path / "out")], stream=model, interactive=False
    )
    assert code == 1 and model.calls == []
    assert "add --yes" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_a_user_openhands_plugin_stops_the_bench(tmp_path, project_venv, capsys, user_plugins_dir):
    (user_plugins_dir / "mine").mkdir(parents=True)
    (user_plugins_dir / "mine" / "README.md").write_text("A plugin.\n")
    model = FakeModel(project_venv)

    assert _run(_bench_file(tmp_path, ONE_ARM), tmp_path / "out", model) == 1

    assert model.calls == []
    captured = capsys.readouterr()
    assert "OpenHands plugins would be loaded" in captured.err and "mine" in captured.err
    assert "Estimated cost:" not in captured.out


def test_the_plan_is_printed_first(tmp_path, project_venv, capsys):
    path = _bench_file(tmp_path, TWO_ARMS, tasks="[temperature-table, page-ranges]", repeats=3)
    bench.bench_main(["--config", path, "--out", str(tmp_path / "o")], interactive=False)
    out = capsys.readouterr().out
    version = task_set_version()
    assert f"Tasks: 2 (task set {version})   Arms: 2   Repeats: 3   Runs: 12" in out
    assert "Estimated cost:" in out


def test_parallel_is_refused_with_a_local_model(tmp_path, project_venv, capsys):
    arms = "  - {name: q, strategy: single, model: local-coder}\n" + ONE_ARM
    assert (
        _run(
            _bench_file(tmp_path, arms),
            tmp_path / "out",
            FakeModel(project_venv),
            "--parallel",
            "2",
        )
        == 1
    )
    assert "local-coder runs locally" in capsys.readouterr().err


def test_parallel_runs_cloud_arms(tmp_path, project_venv):
    model = FakeModel(project_venv)
    path = _bench_file(tmp_path, TWO_ARMS, repeats=2)
    assert _run(path, tmp_path / "out", model, "--parallel", "2") == 0
    assert len(_records(tmp_path / "out")) == 4


def test_runs_are_ordered_repeat_first(tmp_path):
    cfg = load_bench_config(_bench_file(tmp_path, TWO_ARMS, repeats=2))
    assert [p.run_id for p in bench.plan_runs(cfg)] == [
        "a__temperature-table__r1",
        "b__temperature-table__r1",
        "a__temperature-table__r2",
        "b__temperature-table__r2",
    ]


@pytest.mark.parametrize(
    "model, base_url, local",
    [
        ("ollama/qwen3-coder:30b", "", True),
        ("openai/my-model", "http://192.168.1.50:8000", True),
        ("openai/my-model", "http://localhost:1234", True),
        ("deepseek/deepseek-chat", "https://api.deepseek.com", False),
        ("anthropic/claude-sonnet-5-5", "", False),
    ],
)
def test_is_local(model, base_url, local):
    entry = ModelCatalogEntry(name="x", model=model, base_url=base_url)
    assert bench.is_local(entry) is local


def test_list_tasks_needs_no_models(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert bench.bench_main(["--list-tasks"]) == 0
    out = capsys.readouterr().out
    assert f"{len(load_tasks())} tasks" in out and "wordle-score" in out


def test_check_tasks_reports_a_broken_task(tmp_path, monkeypatch):
    broken = tmp_path / "tasks" / "broken"
    shutil.copytree(TASKS["temperature-table"].path, broken)
    # The "reference" now fails its own hidden tests.
    (broken / "reference" / "temperature.py").write_text(
        "def celsius_to_fahrenheit_table(start, stop, step):\n    return []\n"
    )
    monkeypatch.setattr(
        bench, "grade", lambda task, ws: SimpleNamespace(status="failed", summary="1 failed")
    )
    problems = bench.check_tasks(str(tmp_path / "tasks"))
    expected = (
        "broken: the reference solution should have passed its hidden tests, but grading "
        "gave failed (1 failed)"
    )
    assert problems == [expected]


# --- strategy: escalate ---------------------------------------------------------------


class FakeLadderModel(FakeModel):
    """Stands in for stream_task with a ladder: the first rung fails, the
    second solves the task."""

    def __call__(self, task_text, *, cfg, ladder=None, on_message=None):
        from certo.escalation import RungResult

        outcome = super().__call__(task_text, cfg=cfg, on_message=on_message)
        self.ladders = [*getattr(self, "ladders", []), ladder]
        rungs = (
            RungResult(1, ladder.rungs[0].name, "x", "no_progress", 1, 1.0, _summary(0.0)),
            RungResult(2, ladder.rungs[1].name, "y", "verified", 0, 1.0, _summary(0.25)),
        )
        outcome.rungs, outcome.final_rung = rungs, 2
        return outcome


def test_an_escalate_arm_is_recorded_with_its_rungs(tmp_path, project_venv):
    arm = "  - {name: climb, strategy: escalate, models: [local-coder, cloud-a]}\n"
    model = FakeLadderModel(project_venv)
    out = tmp_path / "out"

    assert _run(_bench_file(tmp_path, arm), out, model) == 0

    assert [r.name for r in model.ladders[0].rungs] == ["local-coder", "cloud-a"]
    (record,) = _records(out)
    assert record["strategy"] == "escalate"
    assert record["final_rung"] == 2
    assert [(r["name"], r["verdict"], r["final"]) for r in record["rungs"]] == [
        ("local-coder", "no_progress", False),
        ("cloud-a", "verified", True),
    ]
    assert [m["name"] for m in record["models"]] == ["local-coder", "cloud-a"]
    results = (out / "results.md").read_text()
    assert "- **climb:** rung 2 (cloud-a): 1/1" in results


def test_single_arm_records_have_no_rungs(tmp_path, project_venv):
    out = tmp_path / "out"
    _run(_bench_file(tmp_path, ONE_ARM), out, FakeModel(project_venv))
    (record,) = _records(out)
    assert (record["rungs"], record["final_rung"]) == ([], None)


# --- the plan's cost estimate for escalate arms ---------------------------------

RATED = """
models:
  - name: local-coder
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
    ratings: {reasoning: 2, code: 2, cost: 5}
  - name: local-weak
    model: ollama/tiny
    base_url: http://localhost:11434
    ratings: {reasoning: 1, code: 1, cost: 5}
  - name: cloud-a
    model: anthropic/test-model-a
    api_key: sk-a
    ratings: {reasoning: 3, code: 3, cost: 4}
  - name: cloud-b
    model: openai/test-model-b
    api_key: sk-b
    ratings: {reasoning: 5, code: 5, cost: 2}
"""

LADDER_ARMS = (
    "  - {name: one, strategy: single, model: cloud-a}\n"
    "  - {name: climb, strategy: escalate, models: [local-coder, cloud-a, cloud-b]}\n"
    "  - {name: derived, strategy: escalate}\n"
)

PRICES = {"local-coder": 0.0, "local-weak": 0.0, "cloud-a": 1.0, "cloud-b": 4.0}


def _rated_bench(tmp_path: Path) -> str:
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(tmp_path, RATED)
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        f"tasks: [temperature-table, page-ranges]\nrepeats: 1\narms:\n{LADDER_ARMS}"
    )
    return str(path)


def _earlier(root: Path, records: list[dict]) -> None:
    folder = root / "20260101-000000"
    (folder / "runs").mkdir(parents=True)
    (folder / "meta.json").write_text("{}")
    for i, record in enumerate(records):
        (folder / "runs" / f"{i}.json").write_text(json.dumps(record))


def _single(name: str, model: str, verdict: str | None, error: str | None = None) -> dict:
    return {
        "strategy": "single",
        "models": [{"name": name, "model": model}],
        "verdict": verdict,
        "error": error,
        "rungs": [],
    }


def _plan(tmp_path, monkeypatch, capsys) -> str:
    monkeypatch.setattr(bench, "estimate_run_cost", lambda entry: PRICES[entry.name])
    out = tmp_path / "results" / "new"
    bench.bench_main(["--config", _rated_bench(tmp_path), "--out", str(out)], interactive=False)
    return capsys.readouterr().out


def test_likely_ladder_cost_weights_each_rung_by_the_chance_of_reaching_it():
    # Rung 2 is reached half the time, rung 3 a quarter of the time.
    assert bench.likely_ladder_cost([0.0, 1.0, 4.0], [0.5, 0.5, None]) == 0.5 + 1.0
    assert bench.likely_ladder_cost([0.0, 1.0, 4.0], [0.0, 1.0, None]) == 0.0
    # The last rung's own climb rate doesn't matter; any lower rung's does.
    assert bench.likely_ladder_cost([1.0, 4.0], [1.0, None]) == 5.0
    assert bench.likely_ladder_cost([0.0, 1.0, 4.0], [0.5, None, 0.5]) is None


def test_a_derived_arm_is_planned_and_priced_on_its_ladder_only(tmp_path, monkeypatch, capsys):
    out = _plan(tmp_path, monkeypatch, capsys)
    # local-weak is as cheap as local-coder and weaker: never a rung, never priced.
    assert "derived: escalate, local-coder (" in out
    assert "local-weak" not in out
    assert "derived from the ratings, the same for every task" in out
    # one: 2 x $1; climb: 2 x $5; derived: 2 x $5 (local-coder, cloud-a, cloud-b).
    assert "Estimated cost: at most ~$22.00 (" in out
    assert "no earlier results for local-coder, cloud-a to say more" in out
    assert "likely" not in out


def test_meta_keeps_a_derived_arms_ladder_outside_the_fingerprint(tmp_path):
    from certo.bench_config import load_bench_config

    cfg = load_bench_config(_rated_bench(tmp_path))
    meta = bench._meta(cfg)

    assert meta["ladders"] == {"derived": ["local-coder", "cloud-a", "cloud-b"]}
    assert "ladders" not in meta["config"]


def test_meta_records_each_ollama_models_server(tmp_path, monkeypatch):
    from certo import context_window

    asked = []
    monkeypatch.setattr(
        context_window, "ollama_version", lambda url, *a: asked.append(url) or "0.12.6"
    )
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 131072)
    monkeypatch.setattr(context_window, "ollama_model_digest", lambda *a, **k: "sha256:abc")
    arms = "  - {name: local, strategy: single, model: local-coder, context_tokens: 32768}\n"
    cfg = load_bench_config(_bench_file(tmp_path, arms + ONE_ARM))

    servers = bench._meta(cfg)["model_servers"]

    # Only the Ollama model is asked, once; the cloud arm has no entry.
    assert asked == ["http://localhost:11434"]
    assert servers == {
        "local-coder": {
            "model": "ollama/qwen3-coder:30b",
            "server": "localhost:11434",
            "ollama_version": "0.12.6",
            "model_digest": "sha256:abc",
            "context_tokens": 131072,
            "context_tokens_set": None,
        }
    }


def test_a_silent_ollama_server_is_recorded_as_unknown(tmp_path, monkeypatch):
    from certo import context_window

    loaded = []
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: loaded.append(a))
    arms = "  - {name: local, strategy: single, model: local-coder}\n"
    cfg = load_bench_config(_bench_file(tmp_path, arms))

    info = bench._meta(cfg)["model_servers"]["local-coder"]

    assert info["ollama_version"] is None and info["context_tokens"] is None
    assert info["model_digest"] is None
    assert loaded == []  # no model load is tried on a server that didn't answer


def test_earlier_results_give_a_likely_cost(tmp_path, monkeypatch, capsys):
    _earlier(
        tmp_path / "results",
        [
            # local-coder climbed 1 time in 2; cloud-a 1 time in 4.
            _single("local-coder", "ollama/qwen3-coder:30b", "verified"),
            _single("local-coder", "ollama/qwen3-coder:30b", "retry_exhausted"),
            _single("cloud-a", "anthropic/test-model-a", "verified"),
            _single("cloud-a", "anthropic/test-model-a", "budget_exhausted"),
            {
                "strategy": "escalate",
                "models": [],
                "verdict": "verified",
                "rungs": [
                    {"name": "cloud-a", "model": "anthropic/test-model-a", "verdict": "stuck"},
                    {"name": "cloud-a", "model": "anthropic/test-model-a", "verdict": "verified"},
                ],
            },
            # Another model id under the same name doesn't count.
            _single("local-coder", "ollama/other", "stuck"),
        ],
    )
    out = _plan(tmp_path, monkeypatch, capsys)
    # Per escalation run: 0 + 1.0 x 0.5 + 4.0 x 0.5 x 0.25 = 1.0.
    assert "likely ~$1.00 per run, from 6 earlier run(s) of the lower rungs" in out
    # one 2 x $1 + climb 2 x $1 + derived 2 x $1.
    assert "Estimated cost: at most ~$22.00, likely ~$6.00 (" in out


def test_climb_history_counts_errors_and_provider_failures_as_climbs(tmp_path):
    from certo.bench_config import load_bench_config

    _earlier(
        tmp_path / "results",
        [
            _single("cloud-b", "openai/test-model-b", None, error="RuntimeError: boom"),
            {
                "strategy": "escalate",
                "rungs": [
                    {"name": "cloud-a", "model": "anthropic/test-model-a", "failure": "rate limit"},
                    {"name": "cloud-b", "model": "openai/test-model-b", "verdict": "verified"},
                ],
            },
        ],
    )
    cfg = load_bench_config(_rated_bench(tmp_path))
    assert bench.climb_history(tmp_path / "results", cfg) == {
        "cloud-b": (1, 2),
        "cloud-a": (1, 1),
    }


def test_the_real_cost_is_printed_and_kept_with_the_estimate(tmp_path, project_venv, capsys):
    out = tmp_path / "out"
    _run(_bench_file(tmp_path, ONE_ARM), out, FakeModel(project_venv, cost=0.25))
    printed = capsys.readouterr().out

    meta = json.loads((out / "meta.json").read_text())
    assert set(meta["estimate"]) == {"at_most", "likely"}
    cost = json.loads((out / "cost.json").read_text())
    assert cost["total"] == 0.25 and cost["runs_recorded"] == cost["runs_planned"] == 1
    assert [m["name"] for m in cost["per_model"]] == ["cloud-a"]
    assert "Total cost: $0.2500 (the plan estimated at most ~$" in printed
    assert "## Cost" in (out / "results.md").read_text()


# --- strategy: auto (what `certo --auto-model` does) -------------------------

PROFILES = """
task_profiles:
  tables:
    triggers: [temperature]
    weights: {cost: 3}
  default:
    weights: {reasoning: 3}
"""

AUTO_ARM = "  - {name: picked, strategy: auto, models: [local-coder, cloud-a, cloud-b]}\n"


def _auto_bench(tmp_path: Path, arms: str = AUTO_ARM) -> str:
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(tmp_path, RATED)
    profiles = tmp_path / "task_profiles.yaml"
    profiles.write_text(PROFILES)
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        f"task_profiles_file: {profiles}\n"
        f"tasks: [temperature-table, page-ranges]\nrepeats: 1\narms:\n{arms}"
    )
    return str(path)


class FakeAutoModel(FakeModel):
    """Answers as `stream_task` does with --auto-model: the model it chose,
    from the catalog it was given, in `model_decisions`."""

    def __call__(self, task_text, *, cfg, on_message=None, model_catalog=None):
        from certo.model_catalog import classify_task, rank_for_profile

        outcome = super().__call__(task_text, cfg=cfg, on_message=on_message)
        self.calls[-1].catalog = model_catalog
        profile = classify_task(task_text, model_catalog)
        ranked, _ = rank_for_profile(model_catalog, profile)
        outcome.model_decisions = (
            SimpleNamespace(chosen_name=ranked[0].name, task_profile=profile.name),
        )
        return outcome


def test_an_auto_arm_chooses_from_its_own_models_or_every_active_one(tmp_path):
    arms = AUTO_ARM + "  - {name: any, strategy: auto}\n"
    cfg = load_bench_config(_auto_bench(tmp_path, arms))

    assert cfg.arms[0].models == ["local-coder", "cloud-a", "cloud-b"]
    assert cfg.arms[1].models == ["local-coder", "local-weak", "cloud-a", "cloud-b"]
    assert [p.name for p in cfg.model_catalog.task_profiles] == ["tables", "default"]


@pytest.mark.parametrize(
    ("models", "error"),
    [("[]", "must list the models"), ("[cloud-a, cloud-a]", "twice"), ("[nope]", "unknown model")],
)
def test_an_auto_arms_models_are_checked(tmp_path, models, error):
    from certo.bench_config import BenchConfigError

    arms = f"  - {{name: picked, strategy: auto, models: {models}}}\n"
    with pytest.raises(BenchConfigError, match=error):
        load_bench_config(_auto_bench(tmp_path, arms))


def test_an_auto_run_records_the_model_it_chose_and_the_profile(tmp_path, project_venv):
    model = FakeAutoModel(project_venv)
    out = tmp_path / "out"

    assert _run(_auto_bench(tmp_path), out, model) == 0

    by_task = {r["task"]: r for r in _records(out)}
    assert by_task["temperature-table"]["task_profile"] == "tables"
    assert [m["name"] for m in by_task["temperature-table"]["models"]] == ["local-coder"]
    assert by_task["page-ranges"]["task_profile"] == "default"
    assert [m["name"] for m in by_task["page-ranges"]["models"]] == ["cloud-b"]
    call = model.calls[0]
    assert call.cfg.model_selection == "auto"
    # Only the arm's models are candidates.
    assert [m.name for m in call.catalog.models] == ["local-coder", "cloud-a", "cloud-b"]
    assert "auto from" in (out / "results.md").read_text()
    assert "started on: " in (out / "results.md").read_text()


def test_the_plan_says_which_model_each_auto_run_starts_on(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench, "estimate_run_cost", lambda entry: PRICES[entry.name])
    out = tmp_path / "results" / "new"

    bench.bench_main(["--config", _auto_bench(tmp_path), "--out", str(out)], interactive=False)

    text = capsys.readouterr().out
    assert "picks local-coder for 1 run(s), cloud-b for 1 run(s)" in text
    # At most every candidate per run; likely only the picked one.
    assert "Estimated cost: at most ~$10.00, likely ~$4.00" in text


def test_an_escalate_arm_can_restart_each_rung(tmp_path):
    from certo.bench_config import BenchConfigError

    arms = "  - {name: r, strategy: escalate, models: [cloud-a, cloud-b], handoff: restart}\n"
    cfg = load_bench_config(_bench_file(tmp_path, arms))
    assert cfg.arms[0].params["handoff"] == "restart"
    # The default stays out of params, so older results folders still resume.
    plain_arm = "  - {name: p, strategy: escalate, models: [cloud-a, cloud-b]}\n"
    plain = load_bench_config(_bench_file(tmp_path, plain_arm))
    assert "handoff" not in plain.arms[0].params
    bad = "  - {name: r, strategy: escalate, models: [cloud-a, cloud-b], handoff: rewind}\n"
    with pytest.raises(BenchConfigError, match="'handoff' must be one of"):
        load_bench_config(_bench_file(tmp_path, bad))


def test_a_saved_workspace_leaves_out_the_checkpoint_repository(tmp_path):
    (tmp_path / ".certo" / "checkpoints").mkdir(parents=True)
    (tmp_path / ".certo" / "STATUS.md").write_text("x")
    (tmp_path / "checkpoints").mkdir()  # a project's own folder of that name stays

    shutil.copytree(tmp_path, tmp_path.parent / "copy", ignore=bench._snapshot_ignore)

    copy = tmp_path.parent / "copy"
    assert (copy / ".certo" / "STATUS.md").exists()
    assert not (copy / ".certo" / "checkpoints").exists()
    assert (copy / "checkpoints").exists()


# --- tasks written in milestones ---------------------------------------------

_MILESTONE_TASK = """A tiny module.

## Milestone 1: add
Write add(a, b) in calc.py.
```acceptance
[{"kind": "file_exists", "path": "calc.py"}]
```

## Milestone 2: sub
Write sub(a, b) in calc.py.
```acceptance
[{"kind": "file_contains", "path": "calc.py", "contains": "def sub"}]
```
"""


def _milestone_tasks(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    task = root / "calc"
    (task / "hidden_tests").mkdir(parents=True)
    (task / "reference").mkdir()
    (task / "task.md").write_text(_MILESTONE_TASK)
    (task / "hidden_tests" / "test_calc.py").write_text(
        "from calc import add, sub\n\n\ndef test_both():\n"
        "    assert add(1, 2) == 3 and sub(3, 1) == 2\n"
    )
    (task / "reference" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    return root


def _milestone_bench(tmp_path: Path, arms: str) -> str:
    path = _bench_file(tmp_path, arms, tasks="[calc]")
    text = Path(path).read_text()
    Path(path).write_text(f"tasks_dir: {_milestone_tasks(tmp_path)}\n{text}")
    return path


class FakeMilestoneModel:
    """runner.stream_task for a milestone task: every call writes the
    reference solution and gives the next verdict."""

    def __init__(self, make_venv, tmp_path, verdicts=("verified",)):
        self.make_venv = make_venv
        self.reference = tmp_path / "tasks" / "calc" / "reference" / "calc.py"
        self.verdicts = list(verdicts)
        self.calls: list[SimpleNamespace] = []

    def __call__(self, task_text, *, cfg, on_message=None, acceptance_checks=None):
        self.calls.append(SimpleNamespace(task=task_text, cfg=cfg, checks=acceptance_checks))
        workspace = Path(cfg.workspace)
        shutil.copy(self.reference, workspace / "calc.py")
        if on_message is not None:
            on_message(
                SimpleNamespace(
                    role="tool",
                    name="finish",
                    content=[SimpleNamespace(text=f"Milestone {len(self.calls)} done.")],
                )
            )
        self.make_venv(workspace)
        verdict = self.verdicts[(len(self.calls) - 1) % len(self.verdicts)]
        return SimpleNamespace(
            verification_state=verdict, retries_used=0, run_summary=_summary(0.1)
        )


def test_a_milestones_arm_runs_each_milestone_with_its_checks(tmp_path, project_venv, capsys):
    arms = "  - {name: m, strategy: single, model: cloud-a, milestones: true}\n"
    out = tmp_path / "out"
    model = FakeMilestoneModel(project_venv, tmp_path)
    assert _run(_milestone_bench(tmp_path, arms), out, model) == 0

    assert "(in milestones: the time budget and limits apply to each one)" in (
        capsys.readouterr().out
    )
    assert len(model.calls) == 2
    assert "milestone 1 of 2: add" in model.calls[0].task
    assert "milestone 2 of 2: sub" in model.calls[1].task
    assert "What milestone" not in model.calls[0].task
    assert "- calc.py (6 lines)" in model.calls[1].task
    assert model.calls[1].task.count("Milestone 1 done.") == 1
    assert [c.path for c in model.calls[0].checks] == ["calc.py"]
    assert [c.path for c in model.calls[1].checks] == ["calc.py", "calc.py"]
    (record,) = _records(out)
    assert record["verdict"] == "verified"
    assert record["hidden_tests"]["passed"] is True
    assert [(m["number"], m["verdict"]) for m in record["milestones"]] == [
        (1, "verified"),
        (2, "verified"),
    ]
    assert record["cost"] == pytest.approx(0.2)  # both milestones


def test_a_milestones_arm_stops_at_the_first_milestone_not_verified(tmp_path, project_venv):
    arms = "  - {name: m, strategy: single, model: cloud-a, milestones: true}\n"
    out = tmp_path / "out"
    model = FakeMilestoneModel(project_venv, tmp_path, verdicts=("retry_exhausted",))
    _run(_milestone_bench(tmp_path, arms), out, model)

    assert len(model.calls) == 1
    (record,) = _records(out)
    assert record["verdict"] == "retry_exhausted"
    assert [m["verdict"] for m in record["milestones"]] == ["retry_exhausted"]


def test_combined_attempt_sums_tool_call_reminders_over_every_milestone():
    from certo.bench_strategies import AttemptResult

    attempts = [
        AttemptResult("verified", 0, None, ("cloud-a",), tool_call_reminders=1),
        AttemptResult("verified", 1, None, ("cloud-a",), tool_call_reminders=2),
    ]

    combined = bench._combined_attempt(attempts)

    assert combined.tool_call_reminders == 3


def test_an_arm_without_milestones_gets_the_whole_task_and_every_check(tmp_path, project_venv):
    out = tmp_path / "out"
    model = FakeMilestoneModel(project_venv, tmp_path)
    assert _run(_milestone_bench(tmp_path, ONE_ARM), out, model) == 0

    (call,) = model.calls
    assert "## Milestone 1: add" in call.task and "## Milestone 2: sub" in call.task
    assert "acceptance" not in call.task
    assert [c.path for c in call.checks] == ["calc.py", "calc.py"]
    assert _records(out)[0]["milestones"] is None


def test_a_milestones_arm_needs_tasks_written_in_milestones(tmp_path):
    arms = "  - {name: m, strategy: single, model: cloud-a, milestones: true}\n"
    with pytest.raises(Exception, match="can't be run in milestones: no milestone found"):
        load_bench_config(_bench_file(tmp_path, arms))


def test_milestones_must_be_true_or_false(tmp_path):
    arms = "  - {name: m, strategy: single, model: cloud-a, milestones: 1}\n"
    with pytest.raises(Exception, match="'milestones' must be true or false"):
        load_bench_config(_bench_file(tmp_path, arms))


def test_the_real_stream_passes_acceptance_checks_on(monkeypatch):
    """A milestone task's checks reach runner.stream_task (seen failing live:
    the fakes took the argument, the real stream didn't)."""
    from certo import runner

    seen = {}
    monkeypatch.setattr(runner, "stream_task", lambda task, **kwargs: seen.update(kwargs))
    bench._default_stream("t", cfg=None, acceptance_checks=["check"])
    assert seen["acceptance_checks"] == ["check"]
