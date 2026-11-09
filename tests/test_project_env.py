"""Tests for certo.project_env: each Python project gets its own environment,
used by the agent's terminal and by verification, and Certo's own
environment is never touched. No network: real subprocesses only for venv
creation from the test interpreter; everything else through a fake runner.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from types import SimpleNamespace

import pytest

from certo.verification import prepare_python_env
from certo.project_env import (
    CREATED_MARKER,
    LocalRunner,
    ProjectEnv,
    RunResult,
    WorkspaceRunner,
    ensure_project_env,
    install_into_env,
    terminal_env,
    wants_python_env,
)


class FakeRunner:
    """Records commands; answers from a list of (predicate, RunResult) rules."""

    def __init__(self, tools=None, rules=None, path="/usr/bin:/bin"):
        self.tools = tools or {}
        self.rules = rules or []
        self.commands: list[list[str]] = []
        self.envs: list[dict | None] = []
        self._path = path

    def run(self, command, *, cwd, env=None, timeout):
        self.commands.append(list(command))
        self.envs.append(dict(env) if env else None)
        for predicate, result in self.rules:
            if predicate(list(command)):
                return result
        return RunResult(returncode=0, output="")

    def which(self, name):
        return self.tools.get(name)

    def exec_path(self, host_path):
        return host_path

    def base_path(self):
        return self._path


def _fails(*words):
    return lambda cmd: all(w in " ".join(cmd) for w in words)


# --- Finding or creating the environment -------------------------------------


def test_reuses_an_existing_working_dot_venv(tmp_path, project_venv):
    venv = project_venv(tmp_path)

    setup = ensure_project_env(str(tmp_path))

    assert setup.env is not None
    assert setup.env.host_dir == venv
    scripts, executable = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    assert os.path.normpath(setup.env.python[0]) == os.path.join(venv, scripts, executable)
    assert setup.notices == []


def test_reuses_a_plain_venv_directory(tmp_path):
    runner = FakeRunner()
    (tmp_path / "venv").mkdir()

    setup = ensure_project_env(str(tmp_path), runner)

    assert setup.env.host_dir == str(tmp_path / "venv")
    assert not any("venv" in c and "-m" in c for c in runner.commands)


def test_finds_an_environment_in_a_parent_up_to_the_workspace(tmp_path):
    runner = FakeRunner()
    (tmp_path / ".venv").mkdir()
    nested = tmp_path / "app"
    nested.mkdir()

    setup = ensure_project_env(str(nested), runner, stop_at=str(tmp_path))

    assert setup.env.host_dir == str(tmp_path / ".venv")


def test_a_uv_lock_project_runs_through_uv_run(tmp_path):
    (tmp_path / "uv.lock").write_text("")
    runner = FakeRunner(tools={"uv": "/bin/uv"})

    setup = ensure_project_env(str(tmp_path), runner)

    assert setup.env.kind == "uv"
    assert setup.env.python == ("/bin/uv", "run", "--project", str(tmp_path), "python")
    assert setup.env.venv_dir == str(tmp_path / ".venv")
    assert runner.commands == []  # nothing created; `uv run` syncs on first use


def test_creates_a_dot_venv_with_uv_when_available(tmp_path):
    runner = FakeRunner(tools={"uv": "/bin/uv", "python3": "/usr/bin/python3"})

    setup = ensure_project_env(str(tmp_path), runner)

    assert runner.commands[0][:2] == ["/bin/uv", "venv"]
    assert runner.commands[0][-1] == str(tmp_path / ".venv")
    assert setup.env.host_dir == str(tmp_path / ".venv")
    assert "Created the project environment" in setup.notices[0]


def test_creates_a_dot_venv_with_python_venv_without_uv(tmp_path):
    runner = FakeRunner(tools={"python3": "/usr/bin/python3"})

    ensure_project_env(str(tmp_path), runner)

    assert runner.commands == [
        ["/usr/bin/python3", "-m", "venv", "--clear", str(tmp_path / ".venv")]
    ]


def test_creating_a_real_venv_marks_it_as_certos(tmp_path):
    setup = ensure_project_env(str(tmp_path))

    assert setup.env is not None
    assert (tmp_path / ".venv" / CREATED_MARKER).is_file()
    assert (
        LocalRunner()
        .run([setup.env.python[0], "-c", "pass"], cwd=str(tmp_path), timeout=60)
        .returncode
        == 0
    )


def test_a_broken_venv_certo_did_not_create_is_left_alone(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "keep.txt").write_text("user data")
    runner = FakeRunner(
        tools={"uv": "/bin/uv"},
        rules=[
            (
                _fails("-c", "import sys"),
                RunResult(returncode=None, output="", error="no such file"),
            )
        ],
    )

    setup = ensure_project_env(str(tmp_path), runner)

    assert setup.env is None
    assert "Certo didn't create it" in setup.unavailable_reason
    assert (tmp_path / ".venv" / "keep.txt").exists()
    assert not any(c[:2] == ["/bin/uv", "venv"] for c in runner.commands)


def test_a_broken_venv_certo_created_is_rebuilt(tmp_path):
    # e.g. made inside the Docker container, now seen from the host.
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / CREATED_MARKER).write_text("")
    runner = FakeRunner(
        tools={"uv": "/bin/uv"},
        rules=[(_fails("-c", "import sys"), RunResult(returncode=1, output="exec format error"))],
    )

    setup = ensure_project_env(str(tmp_path), runner)

    assert setup.env is not None
    assert any(c[:2] == ["/bin/uv", "venv"] and "--clear" in c for c in runner.commands)
    assert "Rebuilt" in setup.notices[0]


def test_no_uv_and_no_python_is_a_clear_unavailable_reason(tmp_path):
    setup = ensure_project_env(str(tmp_path), FakeRunner())

    assert setup.env is None
    assert "neither uv nor python3" in setup.unavailable_reason


# --- Installing into the project environment, never Certo's -------------------


def _env(tmp_path) -> ProjectEnv:
    venv = str(tmp_path / ".venv")
    return ProjectEnv(
        kind="venv", host_dir=venv, venv_dir=venv, python=(f"{venv}/bin/python",), install_hint=""
    )


@pytest.mark.parametrize("tools", [{"uv": "/bin/uv"}, {}])
def test_install_targets_the_project_env_never_certos_interpreter(tmp_path, tools):
    runner = FakeRunner(tools=tools)

    install_into_env(_env(tmp_path), runner, "pytest", str(tmp_path))

    (command,) = runner.commands
    joined = " ".join(command)
    assert f"{tmp_path / '.venv'}/bin/python" in joined
    assert sys.executable not in joined
    assert sys.prefix not in joined
    assert command[-1] == "pytest"


def test_prepare_installs_pytest_when_tests_exist_and_records_a_notice(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / "test_app.py").write_text("def test_ok():\n    pass\n")
    probes = iter(["", "pytest"])  # missing, then present after the install
    runner = FakeRunner(tools={"uv": "/bin/uv"})
    real_run = runner.run

    def run(command, **kw):
        if "find_spec" in " ".join(command):
            runner.commands.append(list(command))
            return RunResult(returncode=0, output=next(probes))
        return real_run(command, **kw)

    runner.run = run

    state = prepare_python_env(str(tmp_path), runner)

    assert "pytest" in state.modules
    assert any(c[:3] == ["/bin/uv", "pip", "install"] for c in runner.commands)
    assert any("Installed pytest into the project environment" in n for n in state.notices)


def test_prepare_reports_unavailable_when_the_pytest_install_fails(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / "test_app.py").write_text("def test_ok():\n    pass\n")
    runner = FakeRunner(
        tools={"uv": "/bin/uv"},
        rules=[
            (_fails("find_spec"), RunResult(returncode=0, output="")),
            (_fails("pip", "install"), RunResult(returncode=2, output="error: no network")),
        ],
    )

    state = prepare_python_env(str(tmp_path), runner)

    assert "pytest" not in state.modules
    assert "installing it failed: error: no network" in state.pytest_unavailable_reason


def test_prepare_does_not_install_pytest_without_test_files(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / "main.py").write_text("print(1)\n")
    runner = FakeRunner(rules=[(_fails("find_spec"), RunResult(returncode=0, output=""))])

    state = prepare_python_env(str(tmp_path), runner)

    assert state.has_tests is False
    assert not any("install" in c for c in runner.commands)


# --- Running inside the Docker container --------------------------------------


class _FakeWorkspace:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute_command(self, command, cwd=None, timeout=30.0):
        self.calls.append((command, cwd, timeout))
        return self.result


def _result(**kw):
    base = {"exit_code": 0, "stdout": "", "stderr": "", "timeout_occurred": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_workspace_runner_maps_paths_into_the_container(tmp_path):
    runner = WorkspaceRunner(_FakeWorkspace(_result()), str(tmp_path), "/workspace")

    assert runner.exec_path(str(tmp_path)) == "/workspace"
    assert runner.exec_path(str(tmp_path / "app" / ".venv")) == "/workspace/app/.venv"
    with pytest.raises(ValueError):
        runner.exec_path("/etc")


def test_workspace_runner_runs_with_env_and_closed_stdin(tmp_path):
    workspace = _FakeWorkspace(_result(exit_code=3, stdout="out", stderr="err"))
    runner = WorkspaceRunner(workspace, str(tmp_path), "/workspace")

    result = runner.run(
        ["/workspace/.venv/bin/python", "-m", "pytest", "-q"],
        cwd=str(tmp_path / "app"),
        env={"CI": "true"},
        timeout=99,
    )

    command, cwd, timeout = workspace.calls[0]
    assert command == "env CI=true /workspace/.venv/bin/python -m pytest -q < /dev/null"
    assert cwd == "/workspace/app"
    assert timeout == 99
    assert (result.returncode, result.output) == (3, "outerr")


def test_workspace_runner_reports_a_timeout(tmp_path):
    runner = WorkspaceRunner(
        _FakeWorkspace(_result(exit_code=-1, timeout_occurred=True)), str(tmp_path), "/workspace"
    )

    assert runner.run(["sleep", "9"], cwd=str(tmp_path), timeout=1).timed_out is True


def test_a_docker_venv_is_created_inside_the_container(tmp_path):
    workspace = _FakeWorkspace(_result(stdout="/usr/local/bin/uv\n"))
    runner = WorkspaceRunner(workspace, str(tmp_path), "/workspace")

    setup = ensure_project_env(str(tmp_path), runner)

    commands = [c for c, _cwd, _t in workspace.calls]
    assert any(c.startswith("/usr/local/bin/uv venv") and "/workspace/.venv" in c for c in commands)
    assert setup.env.venv_dir == "/workspace/.venv"
    assert setup.env.python == ("/workspace/.venv/bin/python",)


# --- The agent's terminal -----------------------------------------------------


def test_terminal_env_puts_the_project_venv_first(tmp_path):
    env = terminal_env(_env(tmp_path), FakeRunner(path="/usr/bin"))

    assert env == {
        "VIRTUAL_ENV": str(tmp_path / ".venv"),
        "PATH": f"{tmp_path / '.venv'}/bin:/usr/bin",
    }


def test_local_path_never_includes_certos_own_bin_dir(monkeypatch):
    own = sysconfig.get_path("scripts")
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/usr/bin"]))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert LocalRunner().base_path() == "/usr/bin"


def test_terminal_env_without_a_project_env_clears_certos_virtual_env(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    monkeypatch.setenv("PATH", os.pathsep.join([sysconfig.get_path("scripts"), "/usr/bin"]))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    env = terminal_env(None, LocalRunner())

    assert env == {"PATH": "/usr/bin", "VIRTUAL_ENV": ""}


def test_terminal_env_adds_the_git_ceiling_in_local_runs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalRunner, "base_path", lambda self: "/usr/bin")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    local = terminal_env(_env(tmp_path), LocalRunner(), git_ceiling="/w/projects")
    assert local["GIT_CEILING_DIRECTORIES"] == "/w/projects"
    assert local["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert terminal_env(None, LocalRunner(), git_ceiling="/w/projects") == {
        "GIT_CEILING_DIRECTORIES": "/w/projects"
    }
    # Docker: the paths are the container's.
    elsewhere = terminal_env(_env(tmp_path), FakeRunner(path="/usr/bin"), git_ceiling="/w/projects")
    assert "GIT_CEILING_DIRECTORIES" not in elsewhere


@pytest.mark.parametrize(
    ("task", "language", "files", "expected"),
    [
        ("anything", "python", {"app.py": ""}, True),
        ("Add a Python script", "node", {"package.json": "{}"}, False),
        ("Add a test", "go", {"go.mod": ""}, False),
        ("Create hello.py that prints hello", "unknown", {}, True),
        ("Build a CLI todo app in Python, with tests", "unknown", {}, True),
        ("Build a static landing page", "unknown", {}, False),
        ("Add a Python script", "unknown", {"notes.md": ""}, False),
    ],
)
def test_wants_python_env(tmp_path, task, language, files, expected):
    for name, text in files.items():
        (tmp_path / name).write_text(text)

    assert wants_python_env(task, language, str(tmp_path)) is expected
