"""Each Python project gets its own environment, separate from Certo's.

Certo used to run a project's checks with its own interpreter
(`sys.executable`). That works in the dev virtualenv, where pytest is a dev
dependency, and fails after `uv tool install certo`, whose environment has
no pytest and no pip (see ARCHITECTURE.md's "confident but wrong" list). Both the
agent's terminal and the harness's verification now use one environment
that belongs to the project:

- an existing `.venv/` or `venv/` with a working interpreter, or a `uv.lock`
  project run through `uv run`;
- otherwise a new `.venv` in the project root, made with `uv venv` when uv
  is on PATH, else `python3 -m venv`.

Nothing here ever installs into, or runs checks with, the interpreter Certo
itself runs from.

Commands run through a `CommandRunner`: `LocalRunner` (a host subprocess) or
`WorkspaceRunner` (inside the `--execution docker` container, via the SDK
workspace's `execute_command`). A venv only works on the OS that created it,
so under Docker the environment is created and used inside the container,
by the agent and by verification alike.

Stdlib only: the Docker agent-server image imports this module alongside
`custom_tools` (see docker/agent-server.Dockerfile).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# Written into a venv Certo created, so a venv that later stops working here
# (e.g. one made inside the Docker container, then used on the host) can be
# rebuilt safely. A broken venv without it belongs to someone else and is
# never deleted.
CREATED_MARKER = ".certo-created"

# Python modules a verification plan may use from the project environment.
CHECK_MODULES = ("pytest", "ruff", "mypy")

_SETUP_TIMEOUT_SECONDS = 300
_PROBE_TIMEOUT_SECONDS = 120

# The same directories project detection skips (kept in sync by hand:
# verification.py imports this module, not the other way round).
_SKIP_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    "vendor",
}
_MAX_SCAN_DEPTH = 4

# A task that names Python (or a Python tool) on an empty workspace is about
# to get Python code, so it gets an environment before the agent starts.
_PYTHON_TASK_RE = re.compile(
    r"\b(python3?|pytest|pip|django|flask|fastapi|pydantic|pandas|numpy|poetry|jupyter)\b"
    r"|\.py\b",
    re.IGNORECASE,
)


# --- Where commands run -----------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    returncode: int | None  # None when the command timed out or couldn't start
    output: str
    timed_out: bool = False
    error: str | None = None  # set when the command couldn't be started at all


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None = None,
        timeout: float,
    ) -> RunResult: ...

    def which(self, name: str) -> str | None: ...

    def exec_path(self, host_path: str) -> str: ...

    def base_path(self) -> str: ...


def _certo_scripts_dir() -> str | None:
    """The bin/ directory of the environment Certo runs from, if any.

    Kept off every PATH Certo hands to a project, so `python`/`pip` there can
    never resolve to Certo's own interpreter (e.g. under `uv run certo`, which
    puts it first). A frozen binary has no such directory.
    """
    if getattr(sys, "frozen", False):
        return None
    return sysconfig.get_path("scripts")


class LocalRunner:
    """Runs commands as host subprocesses (`--execution local`, `certo verify`,
    and the agent-facing `run_tests` tool wherever it runs)."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None = None,
        timeout: float,
    ) -> RunResult:
        full_env = None
        if env:
            full_env = {**os.environ, **env}
        try:
            result = subprocess.run(
                list(command),
                check=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                # No human can answer a prompt; a command that reads stdin
                # fails fast instead of hanging (see execute_check).
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _text(exc.stdout) + _text(exc.stderr)
            return RunResult(returncode=None, output=partial, timed_out=True)
        except OSError as exc:
            return RunResult(returncode=None, output="", error=str(exc))
        return RunResult(
            returncode=result.returncode, output=(result.stdout or "") + (result.stderr or "")
        )

    def which(self, name: str) -> str | None:
        found = shutil.which(name)
        own = _certo_scripts_dir()
        if found and own and os.path.dirname(os.path.abspath(found)) == os.path.abspath(own):
            # Certo's own copy (e.g. `python3` under `uv run certo`); look past it.
            return shutil.which(name, path=self.base_path())
        return found

    def exec_path(self, host_path: str) -> str:
        return host_path

    def base_path(self) -> str:
        own = _certo_scripts_dir()
        parts = os.environ.get("PATH", "").split(os.pathsep)
        return os.pathsep.join(
            p for p in parts if p and os.path.normpath(p) != os.path.normpath(own or "")
        )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


class WorkspaceRunner:
    """Runs commands inside the `--execution docker` container through the
    SDK workspace's `execute_command(command, cwd, timeout)`.

    The project directory is bind-mounted, so files are read on the host
    (`host_root`) while commands, paths in commands and the venv itself live
    at `exec_root` (the workspace's `working_dir`, `/workspace`).
    """

    def __init__(self, workspace: Any, host_root: str, exec_root: str) -> None:
        self._workspace = workspace
        self._host_root = os.path.abspath(host_root)
        self._exec_root = exec_root.rstrip("/") or "/"
        self._path: str | None = None

    def exec_path(self, host_path: str) -> str:
        rel = os.path.relpath(os.path.abspath(host_path), self._host_root)
        if rel == ".":
            return self._exec_root
        if rel.startswith(".."):
            raise ValueError(f"{host_path} is outside the mounted workspace {self._host_root}")
        return f"{self._exec_root}/{rel.replace(os.sep, '/')}"

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None = None,
        timeout: float,
    ) -> RunResult:
        prefix = ["env", *(f"{k}={v}" for k, v in (env or {}).items())] if env else []
        line = shlex.join([*prefix, *command]) + " < /dev/null"
        try:
            result = self._workspace.execute_command(
                line, cwd=self.exec_path(cwd), timeout=float(timeout)
            )
        except Exception as exc:  # noqa: BLE001 - a transport error means "couldn't run"
            return RunResult(returncode=None, output="", error=str(exc))
        output = (result.stdout or "") + (result.stderr or "")
        if result.timeout_occurred:
            return RunResult(returncode=None, output=output, timed_out=True)
        return RunResult(returncode=result.exit_code, output=output)

    def which(self, name: str) -> str | None:
        result = self.run(
            ["sh", "-c", f"command -v {shlex.quote(name)}"], cwd=self._host_root, timeout=30
        )
        found = result.output.strip().splitlines()
        if result.returncode == 0 and found and found[-1].startswith("/"):
            return found[-1]
        return None

    def base_path(self) -> str:
        if self._path is None:
            result = self.run(["sh", "-c", 'printf %s "$PATH"'], cwd=self._host_root, timeout=30)
            self._path = result.output.strip() if result.returncode == 0 else ""
            if not self._path:
                self._path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        return self._path


# --- The project environment ------------------------------------------------


@dataclass(frozen=True)
class ProjectEnv:
    """One project's Python environment. Paths are as seen by the runner
    that will use it (host paths locally, container paths under Docker)."""

    kind: str  # "venv" | "uv"
    host_dir: str  # the venv directory, as a host path (for file checks)
    venv_dir: str  # the venv directory, as the runner sees it
    python: tuple[str, ...]  # command prefix that runs the project's python
    install_hint: str  # how to add a dependency, shown to the agent
    windows: bool = False  # the environment's execution platform, not the host's

    def bin_dir(self) -> str:
        directory = self.venv_dir.rstrip("/\\")
        return f"{directory}/{'Scripts' if self.windows else 'bin'}"

    def venv_python(self) -> str:
        return f"{self.bin_dir()}/{'python.exe' if self.windows else 'python'}"

    def env_vars(self, base_path: str) -> dict[str, str]:
        """VIRTUAL_ENV, plus the environment's scripts directory first on PATH."""
        separator = ";" if self.windows else ":"
        return {
            "VIRTUAL_ENV": self.venv_dir,
            "PATH": separator.join(p for p in (self.bin_dir(), base_path) if p),
        }


@dataclass
class EnvSetup:
    """What `ensure_project_env` found or made, and anything worth telling the user."""

    env: ProjectEnv | None
    unavailable_reason: str | None = None
    notices: list[str] = field(default_factory=list)


def _windows_venv(runner: CommandRunner, host_dir: str) -> bool:
    # Docker always executes on Linux, even when its bind mount holds a Windows venv.
    if isinstance(runner, WorkspaceRunner):
        return False
    return os.path.lexists(os.path.join(host_dir, "Scripts", "python.exe")) or (
        isinstance(runner, LocalRunner) and os.name == "nt"
    )


def _env_from_venv(runner: CommandRunner, host_dir: str, uv: str | None) -> ProjectEnv:
    venv_dir = runner.exec_path(host_dir)
    windows = _windows_venv(runner, host_dir)
    scripts, executable, pip = (
        ("Scripts", "python.exe", "pip.exe") if windows else ("bin", "python", "pip")
    )
    python = f"{venv_dir}/{scripts}/{executable}"
    has_pip = os.path.lexists(os.path.join(host_dir, scripts, pip))
    hint = (
        "python -m pip install <package>" if has_pip or uv is None else "uv pip install <package>"
    )
    return ProjectEnv(
        kind="venv",
        host_dir=host_dir,
        venv_dir=venv_dir,
        python=(python,),
        install_hint=hint,
        windows=windows,
    )


def _env_from_uv_project(runner: CommandRunner, project_dir: str, uv: str) -> ProjectEnv:
    host_dir = os.path.join(project_dir, ".venv")
    return ProjectEnv(
        kind="uv",
        host_dir=host_dir,
        venv_dir=runner.exec_path(host_dir),
        python=(uv, "run", "--project", runner.exec_path(project_dir), "python"),
        install_hint="uv add <package> (or uv add --dev <package> for test tools)",
        windows=_windows_venv(runner, host_dir),
    )


def _interpreter_works(runner: CommandRunner, python: str, cwd: str) -> bool:
    result = runner.run([python, "-c", "import sys"], cwd=cwd, timeout=60)
    return result.returncode == 0


def _search_dirs(start: str, stop_at: str | None) -> list[str]:
    """`start`, then each parent up to and including `stop_at`."""
    dirs = [os.path.abspath(start)]
    if stop_at is None:
        return dirs
    stop = os.path.abspath(stop_at)
    current = dirs[0]
    while current != stop and current.startswith(stop + os.sep):
        current = os.path.dirname(current)
        dirs.append(current)
    return dirs


def ensure_project_env(
    project_root: str, runner: CommandRunner | None = None, *, stop_at: str | None = None
) -> EnvSetup:
    """Find the project's environment, or create `.venv` in `project_root`.

    Looks in `project_root` and each parent up to `stop_at` (the workspace
    root) for a `uv.lock` project (used when uv is on PATH) or a `.venv/` /
    `venv/` whose interpreter runs. A broken `.venv` that Certo created is
    rebuilt; one Certo didn't create is left alone and reported.
    """
    runner = runner or LocalRunner()
    uv = runner.which("uv")
    for directory in _search_dirs(project_root, stop_at):
        if uv and os.path.isfile(os.path.join(directory, "uv.lock")):
            return EnvSetup(env=_env_from_uv_project(runner, directory, uv))
        broken: list[str] = []
        for name in (".venv", "venv"):
            host_dir = os.path.join(directory, name)
            if not os.path.isdir(host_dir):
                continue
            env = _env_from_venv(runner, host_dir, uv)
            if _interpreter_works(runner, env.python[0], directory):
                return EnvSetup(env=env)
            broken.append(host_dir)
        for host_dir in broken:
            if os.path.isfile(os.path.join(host_dir, CREATED_MARKER)):
                return _create_venv(
                    runner,
                    directory,
                    uv,
                    rebuilt=True,
                )
        if broken:
            return EnvSetup(
                env=None,
                unavailable_reason=(
                    f"{broken[0]} exists but its Python interpreter doesn't run here, "
                    "and Certo didn't create it, so it was left alone. Recreate it "
                    "(e.g. `python3 -m venv --clear .venv`) or remove it."
                ),
            )
    return _create_venv(runner, os.path.abspath(project_root), uv, rebuilt=False)


def _base_python(runner: CommandRunner) -> str | None:
    """An interpreter to create a venv with: python3/python on PATH.

    Never `sys.executable`: Certo's own interpreter isn't the project's, and
    inside the PyInstaller-frozen Docker agent-server it isn't an
    interpreter at all.
    """
    return runner.which("python3") or runner.which("python")


def _create_venv(
    runner: CommandRunner, directory: str, uv: str | None, *, rebuilt: bool
) -> EnvSetup:
    host_dir = os.path.join(directory, ".venv")
    target = runner.exec_path(host_dir)
    attempts: list[list[str]] = []
    if uv:
        # --seed adds pip, so a habitual `pip install` lands in the venv
        # instead of falling through to some other pip on PATH. It needs
        # pip from the index (or uv's cache); without it, a plain venv.
        attempts.append([uv, "venv", "--seed", "--clear", "--quiet", target])
        attempts.append([uv, "venv", "--clear", "--quiet", target])
    base = _base_python(runner)
    if base:
        attempts.append([base, "-m", "venv", "--clear", target])
    if not attempts:
        return EnvSetup(
            env=None,
            unavailable_reason=(
                "no project environment could be created: neither uv nor python3 is on PATH"
            ),
        )
    errors: list[str] = []
    for command in attempts:
        result = runner.run(command, cwd=directory, timeout=_SETUP_TIMEOUT_SECONDS)
        if result.returncode == 0:
            try:
                with open(os.path.join(host_dir, CREATED_MARKER), "w", encoding="utf-8") as f:
                    f.write("Created by Certo; safe to delete with the rest of this venv.\n")
            except OSError:
                pass
            env = _env_from_venv(runner, host_dir, uv)
            verb = "Rebuilt" if rebuilt else "Created"
            return EnvSetup(
                env=env,
                notices=[f"{verb} the project environment {host_dir} ({command[0]} {command[1]})."],
            )
        errors.append(_last_line(result.error or result.output) or f"exit {result.returncode}")
    return EnvSetup(
        env=None,
        unavailable_reason=(
            f"no project environment could be created in {directory}: " + "; ".join(errors)
        ),
    )


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


# --- What the environment can run -------------------------------------------


_PROBE = (
    f"import importlib.util as u;print(','.join(m for m in {CHECK_MODULES!r} if u.find_spec(m)))"
)


def available_modules(env: ProjectEnv, runner: CommandRunner, cwd: str) -> set[str] | None:
    """Which of CHECK_MODULES the project environment can import, or None if
    the interpreter itself couldn't be run."""
    result = runner.run(
        [*env.python, "-c", _PROBE],
        cwd=cwd,
        env=env.env_vars(runner.base_path()),
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return None
    lines = result.output.strip().splitlines()
    return {m for m in (lines[-1] if lines else "").split(",") if m}


def install_into_env(env: ProjectEnv, runner: CommandRunner, package: str, cwd: str) -> RunResult:
    """Install one package into the project environment — never Certo's.

    uv when it's available (a `uv venv` has no pip unless seeded), else the
    project interpreter's own pip. stdin is closed and the call is bounded.
    """
    uv = runner.which("uv")
    python = env.venv_python()
    if uv:
        command = [uv, "pip", "install", "--quiet", "--python", python, package]
    else:
        command = [python, "-m", "pip", "install", "--quiet", package]
    return runner.run(
        command, cwd=cwd, env=env.env_vars(runner.base_path()), timeout=_SETUP_TIMEOUT_SECONDS
    )


def has_test_files(root: str) -> bool:
    """True when `root` has a file pytest would collect by default
    (`test_*.py` / `*_test.py`), skipping the usual vendored/build dirs."""
    base_depth = root.rstrip(os.sep).count(os.sep)
    for current, dirs, files in os.walk(root):
        if current.rstrip(os.sep).count(os.sep) - base_depth >= _MAX_SCAN_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        if any(
            f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")) for f in files
        ):
            return True
    return False


# --- Before the agent starts ------------------------------------------------


def _workspace_is_empty(root: str) -> bool:
    try:
        entries = os.listdir(root)
    except OSError:
        return True
    return not [e for e in entries if not e.startswith(".")]


def wants_python_env(task: str, language: str, workspace: str) -> bool:
    """Whether the agent should start with a project environment.

    A detected Python project: yes. Any other detected project (Node, Go,
    ...): no, it doesn't get one just for existing. An empty workspace: only
    when the task itself names Python, since that's the code it's about to
    get.
    """
    if language == "python":
        return True
    if language == "unknown" and _workspace_is_empty(workspace):
        return bool(_PYTHON_TASK_RE.search(task))
    return False


def terminal_env(
    env: ProjectEnv | None, runner: CommandRunner, *, git_ceiling: str | None = None
) -> dict[str, str] | None:
    """Extra variables for the agent's terminal session.

    With a project environment: its VIRTUAL_ENV and bin/ first on PATH. In
    every case Certo's own bin/ is dropped from PATH, and a VIRTUAL_ENV that
    points at Certo's own environment is cleared, so the agent can't reach
    Certo's interpreter by accident. With `git_ceiling`
    (project_root.git_ceiling), `git` stops looking for a repository there
    (GIT_CEILING_DIRECTORIES), in local runs only.
    """
    if not isinstance(runner, LocalRunner):
        return env.env_vars(runner.base_path()) if env is not None else None
    extra: dict[str, str] = {}
    if env is not None:
        extra.update(env.env_vars(runner.base_path()))
    else:
        if os.environ.get("PATH", "") != runner.base_path():
            extra["PATH"] = runner.base_path()
        if os.environ.get("VIRTUAL_ENV") and os.path.realpath(
            os.environ["VIRTUAL_ENV"]
        ) == os.path.realpath(sys.prefix):
            extra["VIRTUAL_ENV"] = ""
    if git_ceiling:
        extra["GIT_CEILING_DIRECTORIES"] = git_ceiling
    return extra or None
