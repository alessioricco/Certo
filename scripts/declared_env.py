"""A Python project's environment, built only from what its files declare.

Shared by `fresh_env_grade.py` and `regrade_bench.py`: a saved bench
workspace has no `.venv`, so its packages must be installed again from
`uv.lock`, `pyproject.toml` or `requirements*.txt` before grading. Needs
uv on PATH.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path


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


def run(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    # Never the environment the script runs in (`uv run` sets VIRTUAL_ENV).
    env = {k: v for k, v in (env or os.environ).items() if k != "VIRTUAL_ENV"}
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


def install(project: Path) -> str | None:
    """Make `.venv` from the project's own files; an error line, or None."""
    if (project / "uv.lock").is_file():
        result = run(["uv", "sync", "--frozen", "--quiet"], project)
    else:
        result = run(["uv", "venv", "--quiet", ".venv"], project)
        if result.returncode == 0:
            for source in (
                "pyproject.toml",
                *sorted(p.name for p in project.glob("requirements*.txt")),
            ):
                if (project / source).is_file():
                    result = run(
                        ["uv", "pip", "install", "--quiet", "--python", ".venv", "-r", source],
                        project,
                    )
                    if result.returncode != 0:
                        break
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        return lines[-1] if lines else "install failed"
    result = run(["uv", "pip", "install", "--quiet", "--python", ".venv", "pytest"], project)
    return None if result.returncode == 0 else "could not install pytest"
