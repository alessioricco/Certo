"""Grade a Python bench run again in a fresh environment.

`certo bench` runs a Python task's hidden tests in the project's own
environment, so a package the agent installed by hand and never declared
still passes. This script copies each saved workspace without its
environment, installs only what the project's files declare (`uv.lock`,
`pyproject.toml` or `requirements.txt`), and runs the hidden tests there (see `declared_env.py`).

    uv run python scripts/fresh_env_grade.py bench-results/<run> skill-tasks/yaml-merge

Prints one line per run: what the project declares, and the hidden tests'
result in the fresh environment. Needs uv on PATH. Writes nothing into the
results folder.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from declared_env import declared, install, run

_SKIP = {".venv", "venv", ".certo", ".certo_hidden_tests", "__pycache__", ".pytest_cache", ".git"}


def grade(workspace: Path, hidden: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="certo-fresh-") as tmp:
        project = Path(tmp) / "project"
        shutil.copytree(
            workspace, project, ignore=lambda _d, names: [n for n in names if n in _SKIP]
        )
        error = install(project)
        if error:
            return f"install failed: {error}"
        tests = project / ".certo_hidden_tests"
        shutil.copytree(hidden, tests)
        python = (
            project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        result = run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--rootdir",
                str(tests),
                str(tests),
            ],
            project,
            # As the bench grader: the project's modules import from its root.
            env={**os.environ, "PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        last = (result.stdout.strip().splitlines() or ["no output"])[-1]
        return f"{'passed' if result.returncode == 0 else 'failed'} ({last})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path, help="A certo bench results folder.")
    parser.add_argument("task_dir", type=Path, help="The task's folder (with hidden_tests/).")
    args = parser.parse_args(argv)
    hidden = args.task_dir / "hidden_tests"
    task = args.task_dir.name
    for workspace in sorted((args.out_dir / "workspaces").glob(f"*__{task}__*")):
        print(
            f"{workspace.name}: declares {declared(workspace) or 'nothing'}; fresh: {grade(workspace, hidden)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
