"""run_stats: the measured-runs file and the estimates read from it. No
LLM, no network: summaries are built by hand, the file lives in tmp_path."""

from __future__ import annotations

import csv

from certo import run_stats
from certo.run_stats import (
    COLUMNS,
    describe_error,
    estimate_error,
    estimate_for,
    measured_estimate,
    read_rows,
    record_run,
    stats_path,
)
from certo.run_summary import ModelUsage, RunSummary


def _summary(*models: tuple[str, float], seconds: float = 60.0) -> RunSummary:
    return RunSummary(
        duration_seconds=seconds,
        models=tuple(
            ModelUsage(
                model=m,
                prompt_tokens=1000,
                completion_tokens=100,
                cache_read_tokens=900,
                cost=cost,
            )
            for m, cost in models
        ),
    )


def _row(model="m", kind="task", profile="", cost="0.10", seconds="60", estimate=""):
    return {
        "model": model,
        "kind": kind,
        "profile": profile,
        "cost": cost,
        "seconds": seconds,
        "estimate": estimate,
    }


def test_the_file_is_in_the_users_certo_folder(tmp_path):
    path = stats_path({"XDG_CONFIG_HOME": str(tmp_path)})

    assert path == str(tmp_path / "certo" / "run_stats.csv")


def test_a_run_adds_a_header_once_and_a_line_per_run(tmp_path):
    path = str(tmp_path / "sub" / "run_stats.csv")

    record_run(
        _summary(("anthropic/claude-haiku-5-5", 0.02)),
        kind="task",
        verdict="verified",
        profile="build",
        estimate=0.05,
        path=path,
    )
    record_run(
        _summary(("anthropic/claude-haiku-5-5", 0.03), seconds=90),
        kind="bench",
        verdict="failed",
        path=path,
    )

    lines = (tmp_path / "sub" / "run_stats.csv").read_text().splitlines()
    assert lines[0] == ",".join(COLUMNS)
    rows = read_rows(path)
    assert len(rows) == 2
    first, second = rows
    assert (first["model"], first["kind"], first["profile"], first["verdict"]) == (
        "anthropic/claude-haiku-5-5",
        "task",
        "build",
        "verified",
    )
    assert (first["seconds"], first["cost"], first["estimate"]) == ("60", "0.0200", "0.0500")
    assert (first["input_tokens"], first["cached_tokens"], first["output_tokens"]) == (
        "1000",
        "900",
        "100",
    )
    assert (second["kind"], second["seconds"], second["estimate"]) == ("bench", "90", "")


def test_a_run_on_two_models_has_a_line_each_without_the_time(tmp_path):
    path = str(tmp_path / "run_stats.csv")

    record_run(_summary(("a", 0.01), ("b", 0.2)), kind="task", verdict="verified", path=path)

    rows = read_rows(path)
    assert [r["model"] for r in rows] == ["a", "b"]
    assert [r["seconds"] for r in rows] == ["", ""]


def test_recording_never_raises_and_skips_an_empty_summary(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")

    record_run(
        _summary(("a", 0.01)), kind="task", verdict="verified", path=str(blocker / "run_stats.csv")
    )
    record_run(None, kind="task", verdict="verified", path=str(tmp_path / "x.csv"))
    record_run(
        RunSummary(duration_seconds=1),
        kind="task",
        verdict="verified",
        path=str(tmp_path / "x.csv"),
    )

    assert not (tmp_path / "x.csv").exists()


def test_a_missing_or_broken_file_has_no_rows(tmp_path):
    assert read_rows(str(tmp_path / "none.csv")) == []


def test_no_estimate_with_fewer_than_three_runs():
    rows = [_row(), _row()]

    assert measured_estimate("m", "task", rows=rows) is None


def test_the_estimate_is_the_median_with_the_range():
    rows = [_row(cost=c, seconds=s) for c, s in [("0.10", "60"), ("0.30", "300"), ("0.20", "120")]]
    rows.append(_row(model="other", cost="9"))
    rows.append(_row(kind="bench", cost="9"))

    found = measured_estimate("m", "task", rows=rows)

    assert found is not None
    assert (found.runs, found.cost, found.cost_low, found.cost_high) == (3, 0.2, 0.1, 0.3)
    assert (found.seconds, found.seconds_low, found.seconds_high) == (120, 60, 300)
    assert found.describe() == (
        "~$0.20 per run ($0.10-$0.30), ~2m 00s (1m 00s-5m 00s), from your last 3 task runs"
    )


def test_only_the_last_twenty_runs_count():
    rows = [_row(cost="5")] * 10 + [_row(cost="0.01")] * 20

    found = measured_estimate("m", "task", rows=rows)

    assert found is not None
    assert (found.runs, found.cost_high) == (20, 0.01)


def test_the_profile_narrows_the_estimate_only_with_enough_runs():
    rows = [_row(profile="build", cost="1")] * 3 + [_row(profile="debugging", cost="0.1")] * 2

    narrowed = measured_estimate("m", "task", "build", rows=rows)
    wide = measured_estimate("m", "task", "debugging", rows=rows)

    assert narrowed is not None and (narrowed.profile, narrowed.cost) == ("build", 1.0)
    assert wide is not None and (wide.profile, wide.runs) == ("", 5)


def test_runs_without_a_single_models_time_still_give_a_cost():
    rows = [_row(seconds="")] * 3

    found = measured_estimate("m", "task", rows=rows)

    assert found is not None and found.seconds is None
    assert "per run" in found.describe() and "1m" not in found.describe()


def test_estimate_for_prefers_measured_runs_then_the_guess(monkeypatch):
    monkeypatch.setattr(run_stats, "guess_run_cost", lambda model: 1.5)
    rows = [_row(cost="0.04")] * 3

    assert estimate_for("m", "task", local=False, rows=rows)[0] == 0.04
    assert estimate_for("m", "bench", local=False, rows=rows) == (1.5, None)
    cost, measured = estimate_for("m", "task", local=True, rows=rows)
    assert cost == 0.0 and measured is not None


def test_the_estimate_error_compares_recent_runs_with_earlier_ones():
    earlier = [_row(cost="1", estimate="10")] * 20  # 0.1x
    recent = [_row(cost="4", estimate="10")] * 20  # 0.4x
    no_estimate = [_row(cost="1")] * 5

    error = estimate_error(earlier + no_estimate + recent)

    assert error is not None
    assert (error.runs, error.median_ratio, error.earlier_ratio) == (20, 0.4, 0.1)
    assert describe_error(error) == (
        "Cost estimates, last 20 runs: actual 0.4x the estimate (the 20 before: 0.1x)."
    )


def test_no_estimate_error_without_three_estimated_runs():
    assert estimate_error([_row(estimate="1"), _row(estimate="1"), _row(estimate="0")]) is None


def test_the_file_reads_back_with_the_csv_module(tmp_path):
    path = str(tmp_path / "run_stats.csv")
    record_run(_summary(("a,with comma", 0.01)), kind="task", verdict="verified", path=path)

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["model"] == "a,with comma"


def test_a_finished_run_is_recorded_with_its_kind_and_profile(monkeypatch):
    from types import SimpleNamespace

    from certo import runner

    calls = []
    monkeypatch.setattr(runner, "record_run", lambda summary, **kw: calls.append(kw))
    decision = SimpleNamespace(task_profile="build")
    outcome = SimpleNamespace(
        model_decisions=(decision,), run_summary=_summary(("a", 0.1)), verification_state="verified"
    )

    runner._record_stats(outcome, "# A game\n\n## Now: milestone 2 of 3: Jump\n", None, 0.2)
    runner._record_stats(outcome, "# Fix a bug", None, None)
    runner._record_stats(outcome, "# Fix a bug", "bench", None)

    assert [(c["kind"], c["profile"], c["estimate"]) for c in calls] == [
        ("milestone", "build", 0.2),
        ("task", "build", None),
        ("bench", "build", None),
    ]
