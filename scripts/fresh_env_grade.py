"""Grade a Python bench run again in a fresh environment.

`certo bench` runs a Python task's hidden tests in the project's own
environment, so a package the agent installed by hand and never declared
still passes. This script copies each saved workspace without its
environment, installs only what the project's files declare (`uv.lock`,
`pyproject.toml` or `requirements.txt`), and runs the hidden tests there.

    uv run python scripts/fresh_env_grade.py bench-results/<run> skill-tasks/yaml-merge

Prints one line per run: what the project declares, and the hidden tests'
result in the fresh environment. Needs uv on PATH. Writes nothing into the
results folder.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

_SKIP = {".venv", "venv", ".certo", ".certo_hidden_tests", "__pycache__", ".pytest_cache", ".git"}


def declared(project: Path) -> list[str]:
    """The dependency files the project has, and the packages they list."""
    found = []
    pyproject = project / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            deps = data.get("project", {}).get("dependencies", [])
            found.append(f"pyproject.toml {deps}")
        except tomllib.TOMLDecodeError:
            found.append("pyproject.toml (unreadable)")
    for req in sorted(project.glob("requirements*.txt")):
        lines = [
            line.strip()
            for line in req.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        found.append(f"{req.name} {lines}")
    if (project / "uv.lock").is_file():
        found.append("uv.lock")
    return found


def _run(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    # Never the environment this script runs in (`uv run` sets VIRTUAL_ENV).
    env = {k: v for k, v in (env or os.environ).items() if k != "VIRTUAL_ENV"}
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


def install(project: Path) -> str | None:
    """Make `.venv` from the project's own files; an error line, or None."""
    if (project / "uv.lock").is_file():
        result = _run(["uv", "sync", "--frozen", "--quiet"], project)
    else:
        result = _run(["uv", "venv", "--quiet", ".venv"], project)
        if result.returncode == 0:
            for source in (
                "pyproject.toml",
                *sorted(p.name for p in project.glob("requirements*.txt")),
            ):
                if (project / source).is_file():
                    result = _run(
                        ["uv", "pip", "install", "--quiet", "--python", ".venv", "-r", source],
                        project,
                    )
                    if result.returncode != 0:
                        break
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        return lines[-1] if lines else "install failed"
    result = _run(["uv", "pip", "install", "--quiet", "--python", ".venv", "pytest"], project)
    return None if result.returncode == 0 else "could not install pytest"


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
        result = _run(
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
