"""Grade a `certo bench` results folder's saved projects again, to add the
hidden-test count per milestone to runs made before Certo counted it.

Each run's saved project (`workspaces/<run_id>/`) is copied to a temporary
folder and graded with the task's hidden tests, as the benchmark does. The
record gets `hidden_tests.by_milestone`; its pass or fail stays as it was
graded at the time, and a run whose new grade differs is printed. Then
`results.md` and `results.csv` are written again. No model is called.

A saved project has no `.venv`, so for a Python task that declares its
packages (`uv.lock`, `pyproject.toml`, `requirements*.txt`) they are
installed first, with uv (see `declared_env.py`).

    uv run python scripts/regrade_bench.py bench-results/milestones-local-0.1.27
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from certo.bench import hidden_record
from certo.bench_report import write_report
from certo.bench_tasks import BUILTIN_TASKS_DIR, grade, load_task
from declared_env import declared, install


def regrade(out_dir: Path) -> int:
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    source = meta["task_set"]["source"]
    tasks_dir = BUILTIN_TASKS_DIR if source == "bundled" else Path(source)
    changed = 0
    for path in sorted((out_dir / "runs").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        snapshot = out_dir / "workspaces" / record["run_id"]
        if not snapshot.is_dir():
            print(f"{record['run_id']}: no saved project, left as it is")
            continue
        task = load_task(Path(tasks_dir) / record["task"])
        with tempfile.TemporaryDirectory(prefix="certo-regrade-") as tmp:
            workspace = Path(tmp) / "project"
            shutil.copytree(snapshot, workspace, symlinks=True)
            if task.language == "python" and declared(workspace):
                error = install(workspace)
                if error:
                    print(f"{record['run_id']}: could not install its packages: {error}")
            new = hidden_record(grade(task, workspace))
        if new["passed"] != record["hidden_tests"]["passed"]:
            changed += 1
            print(
                f"{record['run_id']}: graded {new['status']} now, "
                f"{record['hidden_tests']['status']} then; the record keeps the first"
            )
        if "by_milestone" in new:
            record["hidden_tests"]["by_milestone"] = new["by_milestone"]
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"{record['run_id']}: {new['summary']}, per milestone {new.get('by_milestone')}")
    write_report(out_dir)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path, help="A certo bench results folder.")
    args = parser.parse_args()
    changed = regrade(args.out_dir)
    print(f"Report written again. Runs whose grade changed: {changed}.")


if __name__ == "__main__":
    main()
