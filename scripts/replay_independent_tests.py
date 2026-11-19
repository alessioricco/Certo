"""Measure independent tests on saved benchmark projects (TODO.md, section 2).

One writer model writes tests for each bundled task a few times, from the
task text and its starter, exactly as `--independent-tests` does before a
build. Each set of tests then runs on every saved project of that task in
a `certo bench` results folder, whose hidden-test result is known, plus the
task's reference solution and its untouched starter. Only the writing calls
a model; running the tests is free. Saved projects are copied before the
tests run, so the results folders are never changed.

    uv run python scripts/replay_independent_tests.py --model claude-haiku-5-5 \\
        --results bench-results --out bench-results/independent-replay

Stop it at any time and run it again with the same --out: written tests and
finished test runs are kept. The report is <out>/report.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from certo.bench_tasks import BUILTIN_TASKS_DIR, BenchTask, load_tasks, prepare_workspace
from certo.config import ConfigError, load_config
from certo.independent_tests import (
    IndependentTestsResult,
    WrittenTests,
    failing_tests,
    run_independent_tests,
    write_tests,
)
from certo.model_selection import config_for_named_model

_IGNORE = shutil.ignore_patterns(".venv", "venv", "node_modules", "__pycache__")
_lock = threading.Lock()


def _say(text: str) -> None:
    with _lock:
        print(text, flush=True)


def _last_change(task: BenchTask) -> datetime:
    """When the task's text or starter last changed in git."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", "task.md", "starter", "reference"],
        cwd=task.path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return datetime.fromisoformat(out)


def _write_all(tasks: list[BenchTask], cfg, writes: int, out: Path, parallel: int) -> None:
    """Write `writes` sets of tests per task into out/tests/<task>/w<k>/,
    keeping the ones already there."""

    def one(task: BenchTask, k: int) -> None:
        target = out / "tests" / task.name / f"w{k}"
        if (target / "written.json").is_file():
            return
        scratch = Path(tempfile.mkdtemp(prefix="certo-replay-writer-"))
        try:
            written = write_tests(task.prompt, cfg, scratch, project=task.starter_dir)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(written.folder, target)
            cost = sum(m.get("accumulated_cost", 0.0) or 0.0 for m in written.metrics.values())
            meta = {
                "model": written.model,
                "files": list(written.files),
                "language": written.language,
                "hashes": written.hashes,
                "reason": written.reason,
                "cost": cost,
            }
            (target / "written.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            what = ", ".join(written.files) if written.runnable else f"none: {written.reason}"
            _say(f"wrote {task.name} w{k} (${cost:.4f}): {what}")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    jobs = [(t, k) for t in tasks for k in range(1, writes + 1)]
    with ThreadPoolExecutor(parallel) as pool:
        for future in [pool.submit(one, t, k) for t, k in jobs]:
            future.result()


def _load_written(folder: Path) -> WrittenTests | None:
    meta_file = folder / "written.json"
    if not meta_file.is_file():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return WrittenTests(
        folder=folder,
        model=meta["model"],
        files=tuple(meta["files"]),
        language=meta["language"],
        hashes=meta["hashes"],
        reason=meta["reason"],
    )


def _saved_projects(results: Path, tasks: dict[str, BenchTask]) -> list[dict]:
    """Every saved project of a bundled task whose run started after the
    task last changed, with its hidden-test result and verdict."""
    changed = {name: _last_change(t) for name, t in tasks.items()}
    found = []
    for csv_path in sorted(results.glob("*/results.csv")):
        folder = csv_path.parent
        for row in csv.DictReader(csv_path.open(encoding="utf-8")):
            task = row["task"]
            workspace = folder / "workspaces" / row["run_id"]
            if task not in tasks or not workspace.is_dir():
                continue
            if row["hidden_status"] not in ("passed", "failed"):
                continue
            record = folder / "runs" / f"{row['run_id']}.json"
            started = None
            if record.is_file():
                started = json.loads(record.read_text(encoding="utf-8")).get("started_at")
            when = (
                datetime.fromisoformat(started)
                if started
                else datetime.fromtimestamp(csv_path.stat().st_mtime, UTC)
            )
            if when <= changed[task]:
                continue
            found.append(
                {
                    "id": f"{folder.name}/{row['run_id']}",
                    "task": task,
                    "path": str(workspace),
                    "kind": "saved",
                    "hidden": row["hidden_status"],
                    "verdict": row["verdict"],
                    "fooled": row["fooled"] == "True",
                }
            )
    return found


def _bundled_projects(tasks: dict[str, BenchTask], scratch: Path) -> list[dict]:
    """Each task's reference solution (right) and untouched starter (wrong)."""
    found = []
    for name, task in tasks.items():
        for kind, solved in (("reference", True), ("starter", False)):
            path = scratch / f"{name}-{kind}"
            if not path.exists():
                prepare_workspace(task, path, solved=solved)
            found.append(
                {
                    "id": f"{kind}/{name}",
                    "task": name,
                    "path": str(path),
                    "kind": kind,
                    "hidden": "passed" if solved else "failed",
                    "verdict": "",
                    "fooled": False,
                }
            )
    return found


def _run_all(projects: list[dict], out: Path, writes: int, parallel: int) -> None:
    """Run every written test set on every project of its task; one JSON
    line per (project, write) in out/runs.jsonl, keeping finished ones."""
    log = out / "runs.jsonl"
    done = set()
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["project"], row["write"]))

    def one(project: dict) -> None:
        todo = [
            k
            for k in range(1, writes + 1)
            if (project["id"], k) not in done
            and _load_written(out / "tests" / project["task"] / f"w{k}") is not None
        ]
        if not todo:
            return
        copy = Path(tempfile.mkdtemp(prefix="certo-replay-project-")) / "project"
        try:
            shutil.copytree(project["path"], copy, ignore=_IGNORE, symlinks=True)
            for k in todo:
                written = _load_written(out / "tests" / project["task"] / f"w{k}")
                result: IndependentTestsResult = run_independent_tests(written, copy)
                row = {
                    "project": project["id"],
                    "task": project["task"],
                    "kind": project["kind"],
                    "hidden": project["hidden"],
                    "verdict": project["verdict"],
                    "fooled": project["fooled"],
                    "write": k,
                    "status": result.status,
                    "summary": result.summary,
                    "failing": failing_tests(result, limit=20),
                }
                with _lock:
                    with log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row) + "\n")
                _say(f"{project['id']} w{k}: {result.status} ({result.summary})")
        finally:
            shutil.rmtree(copy.parent, ignore_errors=True)

    with ThreadPoolExecutor(parallel) as pool:
        for future in [pool.submit(one, p) for p in projects]:
            future.result()


def _report(out: Path, tasks: list[str], writes: int) -> str:
    """Catch rate and false alarms, overall and per task."""
    rows = [json.loads(x) for x in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    metas = {}
    for task in tasks:
        for k in range(1, writes + 1):
            f = out / "tests" / task / f"w{k}" / "written.json"
            if f.is_file():
                metas[(task, k)] = json.loads(f.read_text(encoding="utf-8"))
    cost = sum(m["cost"] for m in metas.values())
    model = next(iter(metas.values()))["model"] if metas else "?"

    def tally(selected: list[dict]) -> dict[str, int]:
        t = {"runs": len(selected), "failed": 0, "passed": 0, "error": 0, "none": 0}
        for r in selected:
            t[r["status"]] = t.get(r["status"], 0) + 1
        return t

    def line(label: str, selected: list[dict], good: str) -> str:
        t = tally(selected)
        hit = t[good]
        ran = t["passed"] + t["failed"]
        share = f"{hit}/{ran}" if ran else "0/0"
        return f"| {label} | {t['runs']} | {share} | {t['error']} | {t['none']} |"

    wrong = [r for r in rows if r["hidden"] == "failed"]
    right = [r for r in rows if r["hidden"] == "passed"]
    lines = [
        "# Independent tests on saved benchmark projects",
        "",
        f"Writer: `{model}`, {writes} writes per task, total writer cost ${cost:.3f}.",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "## Written tests",
        "",
        "| Task | " + " | ".join(f"w{k}" for k in range(1, writes + 1)) + " |",
        "|---|" + "---|" * writes,
    ]
    for task in tasks:
        cells = []
        for k in range(1, writes + 1):
            m = metas.get((task, k))
            if m is None:
                cells.append("not written")
            elif m["language"]:
                cells.append(f"{len(m['files'])} file(s), ${m['cost']:.3f}")
            else:
                cells.append(f"none ({m['reason'][:60]})")
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Results",
        "",
        "Wrong projects: the independent tests should fail (a catch). Right "
        "projects: they should pass (a failure is a false alarm). Counts are "
        "(project, write) pairs; errors and `none` are left out of the share.",
        "",
        "| Projects | Pairs | Share as expected | Couldn't run | No tests |",
        "|---|---|---|---|---|",
        line(
            "Fooled Certo (verified, hidden failed): caught",
            [r for r in wrong if r["fooled"]],
            "failed",
        ),
        line(
            "All wrong saved projects: caught", [r for r in wrong if r["kind"] == "saved"], "failed"
        ),
        line("Untouched starters: caught", [r for r in wrong if r["kind"] == "starter"], "failed"),
        line("Right saved projects: passed", [r for r in right if r["kind"] == "saved"], "passed"),
        line(
            "Reference solutions: passed", [r for r in right if r["kind"] == "reference"], "passed"
        ),
        "",
        "## Per task",
        "",
        "| Task | Wrong caught | Right passed | Reference passed | Fooled caught |",
        "|---|---|---|---|---|",
    ]

    def share(selected: list[dict], good: str) -> str:
        t = tally(selected)
        ran = t["passed"] + t["failed"]
        return f"{t[good]}/{ran}" if ran else "-"

    for task in tasks:
        mine = [r for r in rows if r["task"] == task]
        lines.append(
            f"| {task} | {share([r for r in mine if r['hidden'] == 'failed' and r['kind'] == 'saved'], 'failed')} "
            f"| {share([r for r in mine if r['hidden'] == 'passed' and r['kind'] == 'saved'], 'passed')} "
            f"| {share([r for r in mine if r['kind'] == 'reference'], 'passed')} "
            f"| {share([r for r in mine if r['fooled']], 'failed')} |"
        )
    alarms: dict[tuple[str, int, str], int] = {}
    for r in right:
        if r["status"] == "failed":
            for name in r["failing"]:
                # Older logs kept pytest's ../../var/... paths.
                name = name.split("::")[-1]
                key = (r["task"], r["write"], name)
                alarms[key] = alarms.get(key, 0) + 1
    on_reference = {
        (r["task"], r["write"])
        for r in rows
        if r["kind"] == "reference" and r["status"] == "failed"
    }
    lines += [
        "",
        "## Failures on right projects, by test",
        "",
        "A test set that also fails the reference solution has a wrong test. "
        "One that passes it may have found a gap the hidden tests miss.",
        "",
        "| Task | Write | Test | Right projects it failed (reference included) | Fails the reference |",
        "|---|---|---|---|---|",
    ]
    for (task, k, name), n in sorted(alarms.items(), key=lambda x: -x[1]):
        wrong_test = "yes" if (task, k) in on_reference else "no"
        lines.append(f"| {task} | w{k} | `{name}` | {n} | {wrong_test} |")
    # Voting: a project counts as failing when at least `need` of its test
    # sets failed (a set that couldn't run counts as not failing).
    by_project: dict[str, list[dict]] = {}
    for r in rows:
        by_project.setdefault(r["project"], []).append(r)

    def voted(pred, need: int) -> str:
        groups = [g for g in by_project.values() if pred(g[0])]
        hit = sum(sum(r["status"] == "failed" for r in g) >= need for g in groups)
        return f"{hit}/{len(groups)}"

    lines += [
        "",
        f"## Voting over the {writes} test sets",
        "",
        "Per project: it is flagged when at least N of its test sets failed.",
        "",
        "| Rule | Fooled caught | Wrong saved caught | Right saved flagged | Reference flagged |",
        "|---|---|---|---|---|",
    ]
    for need in range(1, writes + 1):
        lines.append(
            f"| {need} of {writes} "
            f"| {voted(lambda r: r['fooled'], need)} "
            f"| {voted(lambda r: r['kind'] == 'saved' and r['hidden'] == 'failed', need)} "
            f"| {voted(lambda r: r['kind'] == 'saved' and r['hidden'] == 'passed', need)} "
            f"| {voted(lambda r: r['kind'] == 'reference', need)} |"
        )
    lines += ["", "## Fooled runs", "", "| Project | Write | Result |", "|---|---|---|"]
    for r in sorted((r for r in wrong if r["fooled"]), key=lambda r: (r["project"], r["write"])):
        lines.append(f"| {r['project']} | w{r['write']} | {r['status']}: {r['summary']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", required=True, help="model name from your models.yaml")
    parser.add_argument(
        "--results", default="bench-results", help="folder of `certo bench` results"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--writes", type=int, default=3)
    parser.add_argument("--tasks", nargs="*", help="only these tasks")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--write-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        # The model files the settings name; a ladder problem doesn't stop it.
        cfg = config_for_named_model(load_config(), args.model, "--model")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    tasks = [t for t in load_tasks(BUILTIN_TASKS_DIR) if not args.tasks or t.name in args.tasks]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    _write_all(tasks, cfg, args.writes, out, args.parallel)
    if args.write_only:
        return 0
    by_name = {t.name: t for t in tasks}
    scratch = Path(tempfile.mkdtemp(prefix="certo-replay-bundled-"))
    try:
        projects = _bundled_projects(by_name, scratch) + _saved_projects(
            Path(args.results), by_name
        )
        _say(f"{len(projects)} projects, {args.writes} test sets per task")
        _run_all(projects, out, args.writes, args.parallel)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    report = _report(out, [t.name for t in tasks], args.writes)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
