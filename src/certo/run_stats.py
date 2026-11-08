"""Measured runs, for estimates from real numbers instead of a fixed guess.

Every run appends one line per model it used to `run_stats.csv` in the
user's Certo folder (next to the settings file: `~/.config/certo/`): the
date, the model id, the kind of run (`task`, `milestone` or `bench`), the
task profile `--auto-model` gave it, the verdict, the time, the tokens,
the cost, and the estimate Certo gave before the run (empty when none).
Append-only CSV: no database, model ids only, never a key.

`measured_estimate` reads it back: the median of the last runs of a model
on that kind of run, with the lowest and highest as the range. Pure
standard library; a missing or unreadable file means no history.
"""

from __future__ import annotations

import csv
import io
import math
import os
import statistics
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import user_settings_path
from .model_pricing import guess_run_cost
from .run_summary import RunSummary

FILE_NAME = "run_stats.csv"
COLUMNS = (
    "date",
    "model",
    "kind",
    "profile",
    "verdict",
    "seconds",
    "input_tokens",
    "cached_tokens",
    "output_tokens",
    "cost",
    "estimate",
)
# How many recent runs an estimate reads, and how many it needs.
RECENT_RUNS = 20
MIN_RUNS = 3

_LOCK = threading.Lock()  # parallel bench runs append from threads


def stats_path(environ: Mapping[str, str] | None = None) -> str:
    """`run_stats.csv` in the user's Certo folder (beside the settings file)."""
    return os.path.join(os.path.dirname(user_settings_path(environ)), FILE_NAME)


def record_run(
    summary: RunSummary | None,
    *,
    kind: str,
    verdict: str,
    profile: str = "",
    estimate: float | None = None,
    path: str | None = None,
) -> None:
    """Append one line per model the run used. The run's time goes on the
    line only when one model did all of it. Never raises: the record is a
    convenience, not part of the run."""
    if summary is None or not summary.models:
        return
    path = path or stats_path()
    date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    seconds = f"{summary.duration_seconds:.0f}" if len(summary.models) == 1 else ""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for usage in summary.models:
        writer.writerow(
            [
                date,
                usage.model,
                kind,
                profile,
                verdict,
                seconds,
                usage.prompt_tokens,
                usage.cache_read_tokens,
                usage.completion_tokens,
                f"{usage.cost:.4f}",
                "" if estimate is None else f"{estimate:.4f}",
            ]
        )
    try:
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", encoding="utf-8", newline="") as f:
                if new:
                    f.write(",".join(COLUMNS) + "\n")
                f.write(out.getvalue())
    except OSError:
        pass


def read_rows(path: str | None = None) -> list[dict[str, str]]:
    """Every recorded line, oldest first; none when the file is missing."""
    try:
        with open(path or stats_path(), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def _number(text: str | None) -> float | None:
    try:
        value = float(text or "")
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class MeasuredEstimate:
    """A model's recent runs of one kind: medians and ranges."""

    model: str
    kind: str
    profile: str  # "" when the estimate covers every profile
    runs: int
    cost: float
    cost_low: float
    cost_high: float
    seconds: float | None  # None when no run had a single model's time
    seconds_low: float | None = None
    seconds_high: float | None = None

    def describe(self) -> str:
        """`~$0.02 per run ($0.01-$0.04), ~1m 05s (40s-2m 10s), from 12 task runs`."""
        parts = [f"~${self.cost:.2f} per run (${self.cost_low:.2f}-${self.cost_high:.2f})"]
        if self.seconds is not None:
            parts.append(
                f"~{short_duration(self.seconds)} ({short_duration(self.seconds_low)}-"
                f"{short_duration(self.seconds_high)})"
            )
        what = f"{self.kind} runs" + (f" with profile {self.profile}" if self.profile else "")
        return ", ".join(parts) + f", from your last {self.runs} {what}"


def short_duration(seconds: float | None) -> str:
    seconds = round(seconds or 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def measured_estimate(
    model: str,
    kind: str,
    profile: str = "",
    *,
    rows: list[dict[str, str]] | None = None,
) -> MeasuredEstimate | None:
    """The median cost and time of `model`'s last runs of `kind` (only
    those with `profile`, when it has at least MIN_RUNS of them), or None
    with fewer than MIN_RUNS runs."""
    rows = read_rows() if rows is None else rows
    same = [r for r in rows if r.get("model") == model and r.get("kind") == kind]
    chosen_profile = ""
    if profile:
        with_profile = [r for r in same if r.get("profile") == profile]
        if len(with_profile) >= MIN_RUNS:
            same, chosen_profile = with_profile, profile
    recent = same[-RECENT_RUNS:]
    costs = [c for c in (_number(r.get("cost")) for r in recent) if c is not None]
    if len(costs) < MIN_RUNS:
        return None
    times = [s for s in (_number(r.get("seconds")) for r in recent) if s is not None]
    return MeasuredEstimate(
        model=model,
        kind=kind,
        profile=chosen_profile,
        runs=len(costs),
        cost=statistics.median(costs),
        cost_low=min(costs),
        cost_high=max(costs),
        seconds=statistics.median(times) if times else None,
        seconds_low=min(times) if times else None,
        seconds_high=max(times) if times else None,
    )


@dataclass(frozen=True)
class EstimateError:
    """How far the estimates given before runs were from what they cost."""

    runs: int
    median_ratio: float  # actual / estimate; 1.0 = right, above 1 = too low
    earlier_ratio: float | None  # the same over the runs before those


def estimate_error(rows: list[dict[str, str]] | None = None) -> EstimateError | None:
    """The median actual/estimate ratio over the last RECENT_RUNS paid runs
    that had an estimate, and over the RECENT_RUNS before them, to see
    whether the estimates get closer. None with fewer than MIN_RUNS."""
    rows = read_rows() if rows is None else rows
    ratios = []
    for r in rows:
        estimate, cost = _number(r.get("estimate")), _number(r.get("cost"))
        if estimate and cost is not None and estimate > 0:
            ratios.append(cost / estimate)
    recent = ratios[-RECENT_RUNS:]
    if len(recent) < MIN_RUNS:
        return None
    earlier = ratios[-2 * RECENT_RUNS : -RECENT_RUNS]
    return EstimateError(
        runs=len(recent),
        median_ratio=statistics.median(recent),
        earlier_ratio=statistics.median(earlier) if len(earlier) >= MIN_RUNS else None,
    )


def describe_error(error: EstimateError) -> str:
    """`Cost estimates, last 20 runs: actual 0.4x the estimate (earlier: 0.1x).`"""
    line = f"Cost estimates, last {error.runs} runs: actual {error.median_ratio:.2g}x the estimate"
    if error.earlier_ratio is not None:
        line += f" (the {RECENT_RUNS} before: {error.earlier_ratio:.2g}x)"
    return line + "."


def estimate_for(
    model: str,
    kind: str,
    *,
    local: bool,
    profile: str = "",
    rows: list[dict[str, str]] | None = None,
) -> tuple[float | None, MeasuredEstimate | None]:
    """The cost to expect from one run, and the measured runs it came from:
    nothing for a local model, the median of the measured runs when there
    are enough, else the fixed guess (`guess_run_cost`, measured None)."""
    measured = measured_estimate(model, kind, profile, rows=rows)
    if local:
        return 0.0, measured
    if measured is not None:
        return measured.cost, measured
    return guess_run_cost(model), None
