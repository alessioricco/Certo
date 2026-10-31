"""`certo bench`: run a benchmark file and record every run.

For each task × arm × repeat: a fresh temporary workspace with only the
task's starter files; the arm's strategy runs the normal Certo pipeline on
`task.md`; then the hidden tests are copied in and run in the project's own
environment. One JSON file per run lands in `<out>/runs/`, so an
interrupted benchmark keeps what it has and `--resume` continues it, and
the run's conversation in `<out>/runs/transcripts/`, so every result can
be explained.

Runs are one at a time by default (a local GPU serves one model at a
time); `--parallel N` is allowed only when every arm uses cloud models.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__, context_window
from .banner import _duration
from .bench_config import DEFAULT_BENCH_FILE, Arm, BenchConfig, BenchConfigError, load_bench_config
from .bench_report import arm_rows, cost_line, cost_summary, write_report
from .independent_tests import failing_tests
from .bench_strategies import STRATEGIES, AttemptResult, RunContext, auto_catalog
from .bench_tasks import (
    BUILTIN_TASKS_DIR,
    BenchTask,
    BenchTaskError,
    GradeResult,
    grade,
    load_tasks,
    prepare_workspace,
    task_set_hash,
    task_set_version,
)
from .milestones import (
    MilestoneError,
    MilestonePlan,
    checks_up_to,
    handover,
    milestone_task,
    parse_milestones,
    whole_task,
)
from .run_summary import combine_summaries
from .escalation import ESCALATING_VERDICTS, EscalationError, derive_ladder
from .model_catalog import ModelCatalogError, classify_task, rank_for_profile
from .model_pricing import (
    ESTIMATE_INPUT_TOKENS,
    ESTIMATE_OUTPUT_TOKENS,
    estimate_run_cost,
    is_local,
)

DEFAULT_RESULTS_DIR = "bench-results"
# Verdicts where the agent didn't finish on its own, so it made no claim.
_NO_CLAIM_VERDICTS = ("stuck", "budget_exhausted", "cost_exhausted", "confirmation_required")
_SKIPPED = shutil.ignore_patterns(
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"
)


def _snapshot_ignore(folder: str, names: list[str]) -> set[str]:
    """What a saved workspace leaves out: environments and caches, and the
    checkpoint repository a restart-mode run keeps in `.certo/`."""
    skipped = set(_SKIPPED(folder, names))
    if os.path.basename(folder) == ".certo" and "checkpoints" in names:
        skipped.add("checkpoints")
    return skipped


@dataclass(frozen=True)
class PlannedRun:
    arm: Arm
    task: BenchTask
    repeat: int

    @property
    def run_id(self) -> str:
        return f"{self.arm.name}__{self.task.name}__r{self.repeat}"


def plan_runs(cfg: BenchConfig) -> list[PlannedRun]:
    """Repeat-major order, so a stopped benchmark has a little of every arm
    and task instead of all repeats of the first ones."""
    return [
        PlannedRun(arm, task, repeat)
        for repeat in range(1, cfg.repeats + 1)
        for task in cfg.tasks
        for arm in cfg.arms
    ]


def hardware_hint() -> dict[str, Any]:
    """Enough about this machine to compare numbers from different ones."""
    hint: dict[str, Any] = {
        "system": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }

    def probe(command: list[str]) -> str:
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    if sys.platform == "darwin":
        hint["cpu"] = probe(["sysctl", "-n", "machdep.cpu.brand_string"])
        memory = probe(["sysctl", "-n", "hw.memsize"])
        if memory.isdigit():
            hint["memory_gb"] = round(int(memory) / 2**30)
    elif os.path.isfile("/proc/meminfo"):
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    hint["memory_gb"] = round(int(line.split()[1]) / 2**20)
    if shutil.which("nvidia-smi"):
        gpus = probe(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        if gpus:
            hint["gpu"] = gpus.replace("\n", "; ")
    return {k: v for k, v in hint.items() if v not in ("", None)}


def model_servers(cfg: BenchConfig) -> dict[str, dict[str, Any]]:
    """For every Ollama model the arms use: the server's address (host and
    port), its Ollama version, the digest of the model's build and the
    context window it gives the model by default, or None for what the
    server doesn't say. A local result can
    then be traced to its setup. Never raises: a server that doesn't answer
    is recorded as unknown, and its runs report the failure themselves."""
    servers: dict[str, dict[str, Any]] = {}
    for arm in cfg.arms:
        for name in _plan_models(cfg, arm):
            entry = cfg.catalog.get(name)
            if entry is None or name in servers or not context_window.is_ollama(entry.model):
                continue
            version = context_window.ollama_version(entry.base_url)
            servers[name] = {
                "model": entry.model,
                "server": context_window.server_address(entry.base_url),
                "ollama_version": version,
                "model_digest": context_window.ollama_model_digest(entry.model, entry.base_url)
                if version
                else None,
                # Loading the model can take a while; a silent server is skipped.
                "context_tokens": context_window.ollama_context_tokens(
                    entry.model, entry.base_url, entry.timeout_seconds or 300
                )
                if version
                else None,
                "context_tokens_set": entry.context_tokens or None,
            }
    return servers


def _write_json(path: Path, data: Any) -> None:
    """Write via a temporary file, so a crash never leaves half a file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def hidden_record(graded: GradeResult) -> dict[str, Any]:
    """A run record's `hidden_tests`; `by_milestone` only for a task whose
    hidden tests are named by milestone (milestone -> [passed, total])."""
    record: dict[str, Any] = {
        "status": graded.status,
        "passed": graded.passed,
        "summary": graded.summary,
    }
    if graded.by_milestone:
        record["by_milestone"] = {str(n): list(pt) for n, pt in graded.by_milestone.items()}
    return record


def _milestone_plan(task: BenchTask) -> MilestonePlan | None:
    """The task's milestones, or None for a task not written in milestones."""
    try:
        return parse_milestones(task.prompt)
    except MilestoneError:
        return None


def _combined_attempt(attempts: list[AttemptResult]) -> AttemptResult:
    """One result for a task run in milestones: the last milestone's verdict,
    everything spent added up."""
    last = attempts[-1]
    summaries = [a.run_summary for a in attempts if a.run_summary is not None]
    return AttemptResult(
        verification_state=last.verification_state,
        retries_used=sum(a.retries_used for a in attempts),
        tool_call_reminders=sum(a.tool_call_reminders for a in attempts),
        run_summary=combine_summaries(summaries) if summaries else None,
        models_used=tuple(dict.fromkeys(m for a in attempts for m in a.models_used)),
        rungs=tuple(r for a in attempts for r in a.rungs),
        final_rung=last.final_rung,
        independent_tests=last.independent_tests,
        task_profile=last.task_profile,
    )


def execute_run(
    planned: PlannedRun,
    cfg: BenchConfig,
    out_dir: Path,
    stream: Callable[..., Any],
) -> dict[str, Any]:
    """One isolated run: prepare, run the strategy, grade, record.

    A task written in milestones runs in them when the arm has
    `milestones: true`: the strategy once per milestone, in the same
    folder, until one isn't `verified` (as `certo --milestones`). Any other
    arm gets the whole task at once, without its acceptance blocks, and
    all of their checks."""
    workspace = tempfile.mkdtemp(prefix="certo-bench-")
    isolation = tempfile.mkdtemp(prefix="certo-bench-iso-")
    messages: list[Any] = []
    seconds: list[float] = []
    plan = _milestone_plan(planned.task)
    in_milestones = plan is not None and bool(planned.arm.params.get("milestones"))
    checks: dict[str, Any] = {"now": None}
    milestone_records: list[dict[str, Any]] = []

    def keep(message: Any) -> None:
        messages.append(message)
        seconds.append(round(time.monotonic() - start, 1))

    def recording_stream(task: str, **kwargs: Any) -> Any:
        if checks["now"]:
            kwargs.setdefault("acceptance_checks", checks["now"])
        return stream(task, on_message=keep, **kwargs)

    def context(text: str) -> RunContext:
        return RunContext(
            text,
            workspace,
            cfg.catalog,
            isolation,
            recording_stream,
            model_catalog=cfg.model_catalog,
        )

    try:
        prepare_workspace(planned.task, workspace)
        strategy = STRATEGIES[planned.arm.strategy]
        started_at = _now()
        start = time.monotonic()
        attempt, error, failed_summary = None, None, None
        try:
            if in_milestones:
                attempts = []
                left = None
                for milestone in plan.milestones:
                    checks["now"] = checks_up_to(plan, milestone.number)
                    first_message = len(messages)
                    one = strategy.run(
                        context(milestone_task(plan, milestone.number, left)),
                        planned.arm.params,
                    )
                    attempts.append(one)
                    left = handover(workspace, messages[first_message:], milestone.number)
                    milestone_records.append(
                        {
                            "number": milestone.number,
                            "title": milestone.label,
                            "verdict": one.verification_state,
                            "independent_tests": _independent_record(one.independent_tests),
                        }
                    )
                    if one.verification_state != "verified":
                        break
                attempt = _combined_attempt(attempts)
            else:
                text = planned.task.prompt
                if plan is not None:
                    text = whole_task(plan)
                    checks["now"] = checks_up_to(plan, len(plan))
                attempt = strategy.run(context(text), planned.arm.params)
        except Exception as exc:  # noqa: BLE001 - recorded; the benchmark goes on
            error = f"{type(exc).__name__}: {exc}"
            # runner.stream_task puts the usage recorded up to the error on
            # the exception it raises: a run that worked for 31 minutes and
            # then lost its model server counts what it spent, not zeros.
            failed_summary = getattr(exc, "run_summary", None)
        wall = time.monotonic() - start
        write_transcript(out_dir, planned.run_id, messages, seconds, started_at)
        graded = grade(planned.task, workspace)
        snapshot = out_dir / "workspaces" / planned.run_id
        if snapshot.exists():
            shutil.rmtree(snapshot)
        shutil.copytree(workspace, snapshot, ignore=_snapshot_ignore, symlinks=True)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(isolation, ignore_errors=True)

    verdict = attempt.verification_state if attempt else None
    summary = attempt.run_summary if attempt else failed_summary
    claimed = attempt is not None and verdict not in _NO_CLAIM_VERDICTS
    names = list(attempt.models_used) if attempt else planned.arm.models
    record = {
        "run_id": planned.run_id,
        "arm": planned.arm.name,
        "strategy": planned.arm.strategy,
        "models": [
            {
                "name": n,
                "model": cfg.catalog[n].model,
                "reasoning_effort": cfg.catalog[n].reasoning_effort or None,
            }
            for n in names
        ],
        "task": planned.task.name,
        "repeat": planned.repeat,
        "verdict": verdict,
        "agent_claimed_done": claimed,
        "hidden_tests": hidden_record(graded),
        # Certo said verified, but the hidden tests failed.
        "fooled": verdict == "verified" and not graded.passed,
        # The agent claimed it was done, and Certo did not say verified.
        "caught": claimed and verdict != "verified",
        # Certo did not say verified, but the hidden tests passed: the work
        # was right and Certo couldn't confirm it (e.g. no tests to run).
        "unconfirmed_pass": verdict != "verified" and graded.passed,
        "wall_seconds": round(wall, 1),
        "tokens_in": summary.prompt_tokens if summary else 0,
        "tokens_out": summary.completion_tokens if summary else 0,
        "tokens_cached": summary.cache_read_tokens if summary else 0,
        "cost": round(summary.total_cost, 6) if summary else 0.0,
        "cost_known": summary.cost_complete if summary else True,
        "retries_used": attempt.retries_used if attempt else 0,
        # How often the agent wrote a tool call as text instead of making it
        # (CERTO_TOOL_CALL_REMINDERS); summed over rungs for an escalation.
        "tool_call_reminders": attempt.tool_call_reminders if attempt else 0,
        # How often older steps were summarized (the context window filled up).
        "condensations": summary.condensations if summary else 0,
        # Escalation only: every rung that ran, and which one gave the verdict.
        "rungs": list(attempt.rungs) if attempt else [],
        "final_rung": attempt.final_rung if attempt else None,
        # Auto only: the task profile the task was classified as.
        "task_profile": attempt.task_profile if attempt else None,
        # Arms with independent_tests: their result (report only), or None.
        "independent_tests": _independent_record(attempt.independent_tests if attempt else None),
        # Arms with milestones: true: each milestone that ran, in order.
        "milestones": milestone_records if in_milestones else None,
        "error": error,
        "started_at": started_at,
        "finished_at": _now(),
        "certo_version": __version__,
    }
    _write_json(out_dir / "runs" / f"{planned.run_id}.json", record)
    return record


def _independent_record(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status,
        "summary": result.summary,
        "model": result.model,
        # Each set's result and failing tests, to tell a wrong test from a
        # real bug afterwards (the tests themselves aren't kept).
        "sets": [
            {"status": one.status, "summary": one.summary, "failing": failing_tests(one)}
            for one in result.sets
        ],
    }


def _message_dict(message: Any) -> Any:
    dump = getattr(message, "model_dump", None)
    if not callable(dump):
        return {"text": str(message)}
    try:
        return dump(mode="json")
    except Exception:  # noqa: BLE001 - a transcript must never fail the run
        return {"text": str(message)}


def write_transcript(
    out_dir: Path,
    run_id: str,
    messages: list[Any],
    seconds: list[float] | None = None,
    started_at: str | None = None,
) -> None:
    """Every message of one run (the agent's, the tools', and Certo's own
    notices), as the artifacts transcript stores them. Beside the run
    records, not among them: `load_records` reads only `runs/*.json`.

    `seconds[i]` is when `messages[i]` arrived, counted from `started_at`:
    the only way to see where a long run spent its time (a slow model
    call, a long test run), which the 0.1.15 benchmark couldn't."""
    folder = out_dir / "runs" / "transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"run_id": run_id}
    if started_at is not None:
        data["started_at"] = started_at
    data["messages"] = [_message_dict(m) for m in messages]
    if seconds is not None:
        data["seconds"] = list(seconds)
    _write_json(folder / f"{run_id}.json", data)


def load_records(out_dir: Path) -> list[dict[str, Any]]:
    runs = out_dir / "runs"
    if not runs.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(runs.glob("*.json"))]


def _format_seconds(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{seconds:.0f}s"


def _describe(record: dict[str, Any]) -> str:
    if record["error"]:
        outcome = f"error ({record['error']})"
    else:
        outcome = record["verdict"]
    hidden = "passed" if record["hidden_tests"]["passed"] else record["hidden_tests"]["status"]
    cost = f"${record['cost']:.4f}" if record["cost_known"] else "cost unknown"
    return f"{outcome}; hidden tests {hidden}; {_format_seconds(record['wall_seconds'])}; {cost}"


def _plan_models(cfg: BenchConfig, arm: Arm) -> list[str]:
    """The models an arm's runs can use, in order. For an escalate arm with
    no `models:`, the ladder derived from the ratings (the same for every
    task), not every active model."""
    derived = arm.strategy == "escalate" and arm.params.get("models") is None
    if derived and cfg.model_catalog is not None:
        try:
            return [r.name for r in derive_ladder(cfg.model_catalog).rungs]
        except EscalationError:
            pass
    return list(arm.models)


def climb_history(results_root: Path, cfg: BenchConfig) -> dict[str, tuple[int, int]]:
    """For each model, from earlier results under `results_root`: (runs that
    ended in a verdict an escalation climbs on, runs). A single-arm run and
    each escalation rung count once. Only results of the same model id
    count, so a renamed or changed entry starts over."""
    history: dict[str, list[int]] = {}

    def add(name: str, model: str, climbed: bool) -> None:
        entry = cfg.catalog.get(name)
        if entry is None or entry.model != model:
            return
        counts = history.setdefault(name, [0, 0])
        counts[0] += climbed
        counts[1] += 1

    if not results_root.is_dir():
        return {}
    for folder in sorted(results_root.iterdir()):
        if not (folder / "meta.json").is_file():
            continue
        for record in load_records(folder):
            if record.get("rungs"):
                for rung in record["rungs"]:
                    climbed = rung.get("verdict") in ESCALATING_VERDICTS or bool(
                        rung.get("failure")
                    )
                    add(rung.get("name", ""), rung.get("model", ""), climbed)
            elif record.get("strategy") == "single" and len(record.get("models", [])) == 1:
                model = record["models"][0]
                climbed = record.get("verdict") in ESCALATING_VERDICTS or bool(record.get("error"))
                add(model.get("name", ""), model.get("model", ""), climbed)
    return {name: (c[0], c[1]) for name, c in history.items()}


def likely_ladder_cost(costs: list[float], climb_rates: list[float | None]) -> float | None:
    """The expected cost of one escalation run: each rung's cost times the
    chance that the run gets that far. `climb_rates[i]` is the share of
    earlier runs where rung i's model climbed; None (no history) for any
    rung but the last means there is nothing to estimate from."""
    if any(rate is None for rate in climb_rates[:-1]):
        return None
    total, reach = 0.0, 1.0
    for i, cost in enumerate(costs):
        total += cost * reach
        if i < len(costs) - 1:
            reach *= climb_rates[i]  # type: ignore[operator]
    return total


def _print_plan(
    cfg: BenchConfig, todo: list[PlannedRun], total: int, out_dir: Path
) -> dict[str, float | None]:
    """Print the plan; return the cost estimate, kept in meta.json."""
    print("Benchmark plan")
    version = task_set_version(cfg.tasks_dir)
    print(
        f"  Tasks: {len(cfg.tasks)} (task set {version})   Arms: {len(cfg.arms)}   "
        f"Repeats: {cfg.repeats}   Runs: {total}"
        + (f" ({len(todo)} left to run)" if len(todo) != total else "")
    )
    history = climb_history(out_dir.parent, cfg)
    at_most, likely, unknown = 0.0, 0.0, []
    likely_known = True
    for arm in cfg.arms:
        runs = sum(1 for p in todo if p.arm.name == arm.name)
        names = _plan_models(cfg, arm)
        parts, costs = [], []
        for name in names:
            entry = cfg.catalog[name]
            per_run = estimate_run_cost(entry)
            if per_run == 0.0:
                price = "local, no cost"
            elif per_run is None:
                price = "price unknown"
                unknown.append(name)
            else:
                price = f"~${per_run:.2f} per run"
            costs.append(per_run or 0.0)
            parts.append(f"{name} ({entry.model}, {price})")
        worst = sum(costs)
        at_most += worst * runs
        note = ""
        if arm.strategy == "escalate":
            derived = arm.params.get("models") is None
            rates = [history[n][0] / history[n][1] if n in history else None for n in names]
            expected = likely_ladder_cost(costs, rates)
            notes = ["derived from the ratings, the same for every task"] if derived else []
            notes.append(f"at most ~${worst:.2f} per run if every rung runs")
            if expected is None:
                likely_known = False
                missing = [n for n, r in zip(names[:-1], rates[:-1], strict=True) if r is None]
                notes.append(f"no earlier results for {', '.join(missing)} to say more")
            else:
                seen = sum(history[n][1] for n in names[:-1])
                notes.append(
                    f"likely ~${expected:.2f} per run, from {seen} earlier run(s) of the "
                    "lower rungs"
                )
                likely += expected * runs
            note = f" ({'; '.join(notes)})"
        elif arm.strategy == "auto":
            # One model per run, the one the task's profile ranks first;
            # the others only on a fallback.
            picks = _auto_picks(cfg, arm, [p.task for p in todo if p.arm.name == arm.name])
            likely += sum((estimate_run_cost(cfg.catalog[n]) or 0.0) * c for n, c in picks.items())
            chosen = ", ".join(f"{n} for {c} run(s)" for n, c in picks.items())
            note = f" (picks {chosen}; the others only on a fallback)" if picks else ""
        else:
            likely += worst * runs
        if arm.params.get("independent_tests"):
            note += " (independent tests on; their writing isn't in the estimate)"
        if arm.params.get("context_tokens"):
            note += f" (context window {arm.params['context_tokens']:,} tokens)"
        if arm.params.get("condense") is False:
            note += " (no condensing)"
        if arm.params.get("max_task_seconds"):
            note += f" (time budget {_duration(arm.params['max_task_seconds'])} per run)"
        if arm.params.get("milestones"):
            note += " (in milestones: the time budget and limits apply to each one)"
        if arm.params.get("handoff") == "restart":
            note += " (each rung restarts from the original files)"
        print(f"  {arm.name}: {arm.strategy}, {'; '.join(parts)}, {runs} run(s){note}")
    line = f"  Estimated cost: at most ~${at_most:.2f}"
    if likely_known and abs(likely - at_most) > 0.005:
        line += f", likely ~${likely:.2f}"
    line += (
        f" (rough: assumes ~{ESTIMATE_INPUT_TOKENS // 1000}k input and "
        f"~{ESTIMATE_OUTPUT_TOKENS // 1000}k output tokens per run)"
    )
    if unknown:
        line += f"; no price known for {', '.join(sorted(set(unknown)))}"
    print(line)
    for warning in cfg.catalog_warnings:
        print(f"  Warning (models.yaml): {warning}")
    print(f"  Results: {out_dir}")
    return {
        "at_most": round(at_most, 4),
        "likely": round(likely, 4) if likely_known else None,
    }


def _auto_picks(cfg: BenchConfig, arm: Arm, tasks: list[BenchTask]) -> dict[str, int]:
    """For an `auto` arm: which model each task starts on (the first of its
    profile's ranking), counted per model."""
    if cfg.model_catalog is None:
        return {}
    catalog = auto_catalog(cfg.model_catalog, arm.models)
    picks: dict[str, int] = {}
    for task in tasks:
        try:
            ranked, _ = rank_for_profile(catalog, classify_task(task.prompt, catalog))
        except ModelCatalogError:
            return {}
        picks[ranked[0].name] = picks.get(ranked[0].name, 0) + 1
    return picks


def _confirm(yes: bool, interactive: bool) -> bool:
    if yes:
        return True
    if not interactive:
        print("Not a terminal, so nothing was started: add --yes to run the benchmark.")
        return False
    try:
        answer = input("Start? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    return answer in ("y", "yes")


def _resolve_out_dir(args: argparse.Namespace) -> Path:
    if args.out:
        return Path(args.out)
    if args.resume:
        root = Path(DEFAULT_RESULTS_DIR)
        found = sorted(p for p in root.glob("*") if (p / "meta.json").is_file())
        if not found:
            raise BenchConfigError(
                f"--resume: no earlier results in ./{DEFAULT_RESULTS_DIR}; pass --out DIR."
            )
        return found[-1]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(DEFAULT_RESULTS_DIR) / stamp


def _meta(cfg: BenchConfig) -> dict[str, Any]:
    builtin = Path(cfg.tasks_dir) == BUILTIN_TASKS_DIR
    return {
        "certo_version": __version__,
        "date": _now(),
        "hardware": hardware_hint(),
        "model_servers": model_servers(cfg),
        "task_set": {
            "version": task_set_version(cfg.tasks_dir),
            "hash": task_set_hash(cfg.tasks_dir),
            "source": "bundled" if builtin else cfg.tasks_dir,
        },
        "bench_file": cfg.path,
        "config": cfg.fingerprint(),
        # The ladder a derived escalate arm uses, for the report. Outside
        # `config`, so the --resume fingerprint is unchanged.
        "ladders": {
            a.name: _plan_models(cfg, a)
            for a in cfg.arms
            if a.strategy == "escalate" and a.params.get("models") is None
        },
    }


def _check_out_dir(cfg: BenchConfig, out_dir: Path, resume: bool) -> None:
    """Refuse a results folder that doesn't fit, before anything is asked."""
    meta_path = out_dir / "meta.json"
    if resume:
        if not meta_path.is_file():
            raise BenchConfigError(f"--resume: {out_dir} has no earlier benchmark results.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("config") != cfg.fingerprint() or meta.get("task_set", {}).get(
            "hash"
        ) != task_set_hash(cfg.tasks_dir):
            raise BenchConfigError(
                f"--resume: {out_dir} was made with different tasks, arms, repeats or "
                "models. Use a new --out folder, or restore the original bench file."
            )
    elif meta_path.is_file():
        raise BenchConfigError(
            f"{out_dir} already has benchmark results. Add --resume to continue them, "
            "or choose another --out folder."
        )


def _init_out_dir(cfg: BenchConfig, out_dir: Path, estimate: dict[str, Any]) -> None:
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    if not (out_dir / "meta.json").is_file():
        _write_json(out_dir / "meta.json", {**_meta(cfg), "estimate": estimate})


def _default_stream(
    task: str, *, cfg, ladder=None, on_message=None, model_catalog=None, acceptance_checks=None
) -> Any:
    from .runner import stream_task

    return stream_task(
        task,
        cfg=cfg,
        ladder=ladder,
        on_message=on_message,
        model_catalog=model_catalog,
        acceptance_checks=acceptance_checks,
    )


def run_benchmark(
    cfg: BenchConfig,
    out_dir: Path,
    todo: list[PlannedRun],
    *,
    total: int,
    parallel: int = 1,
    max_cost: float | None = None,
    stop_at: datetime | None = None,
    stream: Callable[..., Any] = _default_stream,
) -> tuple[list[dict[str, Any]], str | None]:
    """Run `todo`; return (new records, why it stopped early: "max-cost",
    "stop-at" or None)."""
    lock = threading.Lock()
    spent = sum(r["cost"] for r in load_records(out_dir))
    done = total - len(todo)
    records: list[dict[str, Any]] = []
    stopped: str | None = None

    def one(planned: PlannedRun) -> None:
        nonlocal spent, done, stopped
        with lock:
            if stopped:
                return
            if max_cost is not None and spent >= max_cost:
                stopped = "max-cost"
                return
            if stop_at is not None and _local_now() >= stop_at:
                stopped = "stop-at"
                return
        record = execute_run(planned, cfg, out_dir, stream)
        with lock:
            spent += record["cost"]
            done += 1
            records.append(record)
            print(
                f"[{done}/{total}] {planned.arm.name} · {planned.task.name} · "
                f"r{planned.repeat}: {_describe(record)}",
                flush=True,
            )

    if parallel <= 1:
        for planned in todo:
            one(planned)
            if stopped:
                break
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(one, p) for p in todo]
            try:
                for future in futures:
                    future.result()
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                raise
    return records, stopped


def _local_now() -> datetime:
    return datetime.now()


def parse_stop_at(value: str, now: datetime) -> datetime:
    """The next local time `value` (HH:MM, 24-hour) after `now`: today if
    it is still ahead, else tomorrow."""
    try:
        wanted = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise BenchConfigError(
            f"--stop-at must be a 24-hour time like 07:00, not {value!r}."
        ) from None
    when = datetime.combine(now.date(), wanted)
    return when if when > now else when + timedelta(days=1)


def build_bench_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo bench",
        description=(
            "Compare models and strategies on Certo's bundled tasks, each graded by "
            "hidden tests the agent never sees. Models are named from models.yaml; "
            ".env is never read."
        ),
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_BENCH_FILE,
        help=f"The benchmark file (default: {DEFAULT_BENCH_FILE}).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=f"Results folder (default: ./{DEFAULT_RESULTS_DIR}/<date-time>).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an interrupted benchmark in --out (default: the latest results "
        "folder), skipping runs already recorded.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run N at a time. Only when every arm uses cloud models (default: 1).",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=None,
        metavar="USD",
        help="Stop starting new runs once the recorded cost reaches USD; results so far are kept.",
    )
    parser.add_argument(
        "--stop-at",
        default=None,
        metavar="HH:MM",
        help="Stop starting new runs at this local time (24-hour; tomorrow if already past "
        "today). Runs in progress finish; continue later with --resume.",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Start without asking to confirm the plan."
    )
    parser.add_argument(
        "--list-tasks", action="store_true", help="List the tasks and exit, with no model."
    )
    parser.add_argument(
        "--check-tasks",
        action="store_true",
        help="Check every task with no model: its reference solution must pass its hidden "
        "tests and its starter alone must fail them.",
    )
    return parser


def _tasks_dir_from(config_path: str) -> str:
    """The task folder for --list-tasks/--check-tasks: the bench file's
    tasks_dir if the file exists and sets one, else the bundled set."""
    import yaml

    path = Path(config_path)
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("tasks_dir"), str):
            return raw["tasks_dir"]
    return str(BUILTIN_TASKS_DIR)


def _list_tasks(tasks_dir: str) -> int:
    tasks = load_tasks(tasks_dir)
    print(
        f"Task set {task_set_version(tasks_dir)} ({task_set_hash(tasks_dir)}), {len(tasks)} tasks:"
    )
    for task in tasks:
        first = next((ln.lstrip("# ").strip() for ln in task.prompt.splitlines() if ln.strip()), "")
        print(f"  {task.name:<22} {task.language:<7} {first}")
    return 0


def check_tasks(tasks_dir: str) -> list[str]:
    """Problems with a task set, or [] when every task is valid."""
    problems = []
    for task in load_tasks(tasks_dir):
        for solved, wanted in ((True, "passed"), (False, "failed")):
            workspace = tempfile.mkdtemp(prefix="certo-bench-check-")
            try:
                prepare_workspace(task, workspace, solved=solved)
                result = grade(task, workspace)
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
            if result.status != wanted:
                which = "reference solution" if solved else "starter alone"
                problems.append(
                    f"{task.name}: the {which} should have {wanted} its hidden tests, but "
                    f"grading gave {result.status} ({result.summary})"
                )
    return problems


def _check_tasks(tasks_dir: str) -> int:
    problems = check_tasks(tasks_dir)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"All {len(load_tasks(tasks_dir))} tasks are valid.")
    return 0


def bench_main(
    argv: list[str],
    *,
    stream: Callable[..., Any] = _default_stream,
    interactive: bool | None = None,
) -> int:
    args = build_bench_parser().parse_args(argv)
    on_terminal = sys.stdin.isatty() if interactive is None else interactive
    try:
        if args.list_tasks:
            return _list_tasks(_tasks_dir_from(args.config))
        if args.check_tasks:
            return _check_tasks(_tasks_dir_from(args.config))
        if args.parallel < 1:
            raise BenchConfigError("--parallel must be at least 1.")
        if args.max_cost is not None and args.max_cost <= 0:
            raise BenchConfigError("--max-cost must be greater than 0.")
        stop_at = parse_stop_at(args.stop_at, _local_now()) if args.stop_at else None
        cfg = load_bench_config(args.config)
        local = sorted({n for a in cfg.arms for n in a.models if is_local(cfg.catalog[n])})
        if args.parallel > 1 and local:
            raise BenchConfigError(
                f"--parallel needs cloud models only; {', '.join(local)} runs locally, and "
                "a local server serves one model at a time. Run without --parallel."
            )
        out_dir = _resolve_out_dir(args)
        planned = plan_runs(cfg)
        recorded = {r["run_id"] for r in load_records(out_dir)} if args.resume else set()
        todo = [p for p in planned if p.run_id not in recorded]
        _check_out_dir(cfg, out_dir, args.resume)
    except (BenchConfigError, BenchTaskError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    from .plugins import foreign_plugins, refusal

    found = foreign_plugins(None)
    if found:
        print(f"Error: {refusal(found)}", file=sys.stderr)
        return 1

    estimate = _print_plan(cfg, todo, len(planned), out_dir)
    if not todo:
        print("Every run is already recorded.")
    elif not _confirm(args.yes, on_terminal):
        return 1
    _init_out_dir(cfg, out_dir, estimate)
    if stop_at is not None and todo:
        print(f"No new run starts after {stop_at:%Y-%m-%d %H:%M}.")

    interrupted = False
    stopped: str | None = None
    try:
        _, stopped = run_benchmark(
            cfg,
            out_dir,
            todo,
            total=len(planned),
            parallel=args.parallel,
            max_cost=args.max_cost,
            stop_at=stop_at,
            stream=stream,
        )
    except KeyboardInterrupt:
        interrupted = True
    records = load_records(out_dir)
    finish_report(cfg, out_dir, records)
    if stopped == "max-cost":
        print(f"Stopped: the recorded cost reached --max-cost ${args.max_cost:.2f}.")
    elif stopped == "stop-at":
        print(f"Stopped: it is past --stop-at {stop_at:%H:%M}.")
    if interrupted:
        print(
            "Interrupted. Finished runs are kept; continue with: certo bench --resume "
            f"--out {out_dir}"
        )
        return 130
    left = len(planned) - len(records)
    if left:
        print(f"{left} run(s) not done. Continue with: certo bench --resume --out {out_dir}")
    return 0


def finish_report(cfg: BenchConfig, out_dir: Path, records: list[dict[str, Any]]) -> None:
    """Write results.md and results.csv, and print the per-arm summary."""
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    markdown = write_report(out_dir)
    print(f"\n{len(records)}/{len(plan_runs(cfg))} runs recorded.")
    for row in arm_rows(meta, records):
        print(
            f"  {row['Arm']}: hidden tests passed {row['Hidden tests passed']}, verified "
            f"{row['Verified']}, fooled {row['Fooled']}, caught {row['Caught']}, "
            f"cost {row['Cost']}"
        )
    print(cost_line(cost_summary(meta, records)))
    transcripts = (
        "; conversations in runs/transcripts/"
        if (out_dir / "runs" / "transcripts").is_dir()
        else ""
    )
    print(f"Results: {markdown} (and results.csv, cost.json{transcripts})")
