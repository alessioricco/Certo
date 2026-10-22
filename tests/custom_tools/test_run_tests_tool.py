"""Tests for the language-neutral verification pipeline (detect -> discover
plan -> execute -> aggregate) plus the agent-facing RunTestsTool executor.
No LLM, no network — real subprocesses only for tools actually installed in
this dev environment (pytest, npm, ruff, go, cargo — each gated by a
skip-if-missing marker matching the project's own convention), everything
else exercised via constructed `CheckSpec`s or monkeypatched `shutil.which`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys

import pytest

from certo.custom_tools.run_tests_tool import RunTestsAction, RunTestsExecutor
from certo.verification import (
    CheckOutcome,
    CheckSpec,
    ProjectDetection,
    PythonEnvState,
    VerificationRun,
    _entrypoint_ordering_spec,
    _find_python_entrypoints,
    _mypy_configured,
    _npm_test_script,
    _python_plan,
    _ruff_configured,
    detect_project,
    discover_verification_plan,
    execute_check,
    run_full_verification,
)
from certo.project_env import LocalRunner, ProjectEnv, RunResult, _base_python

_FIXTURE = """
def test_ok():
    assert True

def test_broken():
    assert 1 == 2, "boom"
"""

_requires_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="npm not installed")
_requires_go = pytest.mark.skipif(shutil.which("go") is None, reason="go not installed")
_requires_cargo = pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")


def _write_fixture(tmp_path):
    test_file = tmp_path / "test_fixture.py"
    test_file.write_text(_FIXTURE)
    return test_file


def _write_package_json(tmp_path, scripts):
    (tmp_path / "package.json").write_text(json.dumps({"name": "fixture", "scripts": scripts}))


def _state(tmp_path, modules=("pytest",), *, has_tests=True) -> PythonEnvState:
    """A prepared environment for planning tests. The test interpreter stands
    in for the project's (planning only builds commands from it)."""
    env = ProjectEnv(
        kind="venv",
        host_dir=str(tmp_path / ".venv"),
        venv_dir=str(tmp_path / ".venv"),
        python=(sys.executable,),
        install_hint="python -m pip install <package>",
    )
    return PythonEnvState(env=env, modules=set(modules), has_tests=has_tests, base_path="/usr/bin")


def test_reports_pass_and_fail_counts(tmp_path, project_venv):
    project_venv(tmp_path)
    _write_fixture(tmp_path)
    executor = RunTestsExecutor(str(tmp_path))

    observation = executor(RunTestsAction())

    assert observation.check_kind == "pytest"
    assert observation.exit_code == 1
    assert observation.passed == 1
    assert observation.failed == 1
    assert observation.errors == 0
    assert observation.failures == ["test_fixture.py::test_broken - AssertionError: boom"]
    assert "1 failed" in observation.summary
    assert "1 passed" in observation.summary


def test_can_target_a_single_node_id(tmp_path, project_venv):
    project_venv(tmp_path)
    _write_fixture(tmp_path)
    executor = RunTestsExecutor(str(tmp_path))

    observation = executor(RunTestsAction(path="test_fixture.py::test_ok"))

    assert observation.exit_code == 0
    assert observation.passed == 1
    assert observation.failed == 0
    assert observation.failures == []


def test_all_passing_has_no_failures(tmp_path, project_venv):
    project_venv(tmp_path)
    (tmp_path / "test_fixture.py").write_text("def test_ok():\n    assert True\n")
    executor = RunTestsExecutor(str(tmp_path))

    observation = executor(RunTestsAction())

    assert observation.exit_code == 0
    assert observation.passed == 1
    assert observation.failed == 0
    assert observation.errors == 0
    assert observation.failures == []
    assert "1 passed" in observation.summary


def test_base_python_for_a_new_venv_comes_from_path_when_frozen(monkeypatch):
    # Regression test: sys.executable inside a PyInstaller-frozen process (the
    # Docker agent-server image) resolves to the frozen binary itself, not a
    # Python interpreter — using it there silently re-invoked the agent-server
    # binary instead of running pytest. The project venv is now created from
    # python3 on PATH, frozen or not.
    from certo.project_env import LocalRunner

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "shutil.which", lambda name, path=None: f"/usr/bin/{name}" if name == "python3" else None
    )

    assert _base_python(LocalRunner()) == "/usr/bin/python3"


def test_run_tests_tool_reports_pytest_unavailable_instead_of_failing(tmp_path, monkeypatch):
    # No project environment can be made (no uv, no python3): the tool says
    # so plainly instead of running pytest with Certo's own interpreter.
    _write_fixture(tmp_path)
    monkeypatch.setattr("shutil.which", lambda _name, path=None: None)

    observation = RunTestsExecutor(str(tmp_path))(RunTestsAction())

    assert observation.check_kind == "none"
    assert "neither uv nor python3" in observation.summary


def test_run_tests_tool_generic_path_covers_go(tmp_path, monkeypatch):
    # The agent-facing tool's contract (always exactly one check) must hold
    # for languages beyond Python/Node too — exercised here against a real
    # go.mod with `go` monkeypatched unavailable, so it's deterministic and
    # fast regardless of whether this environment has Go installed.
    (tmp_path / "go.mod").write_text("module example.com/thing\n\ngo 1.21\n")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    executor = RunTestsExecutor(str(tmp_path))

    observation = executor(RunTestsAction())

    assert observation.check_kind == "go"
    assert "not installed" in observation.summary


def test_run_tests_tool_generic_path_covers_ambiguous_monorepo(tmp_path):
    # The agent-facing tool must not silently pick one of several candidate
    # projects either — same generic (detect -> discover -> execute) path
    # as Go/Rust/Java above.
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _write_package_json(frontend, {"build": "vite build"})
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[project]\nname = 'backend'\n")
    executor = RunTestsExecutor(str(tmp_path))

    observation = executor(RunTestsAction())

    assert observation.check_kind == "ambiguous"
    assert "ambiguous" in observation.summary


def _runner_failing(monkeypatch, match, result):
    """Make LocalRunner.run return `result` for commands containing `match`;
    every other command (project setup) runs for real."""
    real = LocalRunner.run

    def run(self, command, **kwargs):
        if match in " ".join(command):
            return result
        return real(self, command, **kwargs)

    monkeypatch.setattr(LocalRunner, "run", run)


_TIMED_OUT = RunResult(returncode=None, output="still waiting...", timed_out=True)
_CANT_START = RunResult(returncode=None, output="", error="No such file or directory")


@pytest.mark.parametrize(
    ("result", "expected"),
    [(_TIMED_OUT, "pytest timed out after 300s"), (_CANT_START, "pytest could not be run")],
)
def test_run_tests_tool_reports_a_pytest_timeout_or_start_failure(
    tmp_path, project_venv, monkeypatch, result, expected
):
    project_venv(tmp_path)
    _write_fixture(tmp_path)
    _runner_failing(monkeypatch, "-m pytest", result)

    observation = RunTestsExecutor(str(tmp_path))(RunTestsAction())

    assert observation.check_kind == "none"
    assert expected in observation.summary


@pytest.mark.parametrize(
    ("result", "expected"),
    [(_TIMED_OUT, "npm run build timed out"), (_CANT_START, "npm could not run")],
)
def test_run_tests_tool_reports_an_npm_timeout_or_start_failure(
    tmp_path, monkeypatch, result, expected
):
    _write_package_json(tmp_path, {"build": "vite build"})
    monkeypatch.setattr(LocalRunner, "which", lambda self, name: "/usr/bin/npm")
    _runner_failing(monkeypatch, "run build", result)

    observation = RunTestsExecutor(str(tmp_path))(RunTestsAction())

    assert observation.exit_code == 1
    assert expected in observation.summary


def test_run_tests_tool_shows_a_go_timeout_as_a_failure_with_its_output(tmp_path, monkeypatch):
    # The generic path used to report exit code 0 for a timeout, which
    # hid the output from the agent.
    (tmp_path / "go.mod").write_text("module example.com/thing\n\ngo 1.21\n")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/go")
    _runner_failing(monkeypatch, "go test", _TIMED_OUT)

    observation = RunTestsExecutor(str(tmp_path))(RunTestsAction())

    assert observation.exit_code == 1
    assert "timeout" in observation.summary
    assert "still waiting..." in observation.to_llm_content[0].text


# --- Stage 1: project detection ---------------------------------------------


def test_detects_python_via_pyproject_toml(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path))


def test_detects_python_via_bare_source_files_when_no_manifest(tmp_path):
    # Preserves the original always-try-pytest default: this repo's own
    # fixture tests, and plenty of small real scripts, have no
    # pyproject.toml at all.
    (tmp_path / "test_fixture.py").write_text("def test_ok():\n    assert True\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path))


def test_bare_python_root_is_the_folder_that_holds_every_source_folder(tmp_path):
    # The live Hanoi layout: a package and a sibling tests/ folder, no
    # manifest. Rooting at the package (the first folder walked) made
    # pytest collect nothing.
    (tmp_path / "hanoi").mkdir()
    (tmp_path / "hanoi" / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_game.py").write_text("def test_ok():\n    assert True\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path))


def test_bare_python_root_stays_in_the_only_source_folder(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("")
    (tmp_path / "README.md").write_text("")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path / "app"))


def test_detects_node_via_package_json(tmp_path):
    _write_package_json(tmp_path, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="node", root=str(tmp_path))


def test_detects_go_via_go_mod(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/thing\n\ngo 1.21\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="go", root=str(tmp_path))


def test_detects_rust_via_cargo_toml(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "fixture"\nversion = "0.1.0"\n')

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="rust", root=str(tmp_path))


def test_detects_java_maven_via_pom_xml(tmp_path):
    (tmp_path / "pom.xml").write_text("<project></project>\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="java-maven", root=str(tmp_path))


def test_detects_java_gradle_via_build_gradle(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="java-gradle", root=str(tmp_path))


def test_detects_java_gradle_via_kotlin_dsl(tmp_path):
    (tmp_path / "build.gradle.kts").write_text("plugins { java }\n")

    detection = detect_project(str(tmp_path))

    assert detection.language == "java-gradle"


def test_unknown_project_has_no_recognizable_markers(tmp_path):
    (tmp_path / "README.md").write_text("just some notes, no code here\n")

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="unknown", root=str(tmp_path))


def test_empty_directory_is_unknown(tmp_path):
    detection = detect_project(str(tmp_path))

    assert detection.language == "unknown"


def test_python_markers_win_over_a_sibling_package_json(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    _write_package_json(tmp_path, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection.language == "python"


def test_finds_a_marker_nested_below_the_workspace_root(tmp_path):
    # Confirmed live: `npm create vite@latest <name>` nested the actual app
    # under <project>/<name>/<name>/, one or two levels below the --project
    # workspace root.
    nested = tmp_path / "outer" / "inner"
    nested.mkdir(parents=True)
    _write_package_json(nested, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="node", root=str(nested))


def test_sibling_projects_at_the_same_depth_are_ambiguous(tmp_path):
    # A monorepo/workspace with two unrelated applications, neither at the
    # workspace root — no single obvious project to verify.
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _write_package_json(frontend, {"build": "vite build"})
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[project]\nname = 'backend'\n")

    detection = detect_project(str(tmp_path))

    assert detection.language == "ambiguous"
    assert detection.root == str(tmp_path)
    assert detection.candidates is not None
    assert set(detection.candidates) == {
        ("node", str(frontend)),
        ("python", str(backend)),
    }


def test_ambiguous_candidates_are_reported_regardless_of_directory_listing_order(tmp_path):
    # Two candidates at the same depth, same languages, different names —
    # confirms the walk collects every match at the shallowest depth rather
    # than stopping at the first one a DFS happens to visit.
    app_a = tmp_path / "app-a"
    app_a.mkdir()
    _write_package_json(app_a, {"build": "vite build"})
    app_b = tmp_path / "app-b"
    app_b.mkdir()
    _write_package_json(app_b, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection.language == "ambiguous"
    assert set(detection.candidates) == {
        ("node", str(app_a)),
        ("node", str(app_b)),
    }


def test_explicit_root_with_its_own_manifest_is_not_ambiguous(tmp_path):
    # The workspace root itself is the intended project (e.g. CERTO_WORKSPACE
    # /--project already points at it) — a nested manifest elsewhere (a
    # vendored dependency, an example) must not turn this into "ambiguous".
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    vendored = tmp_path / "vendor" / "some-lib"
    vendored.mkdir(parents=True)
    _write_package_json(vendored, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path))


def test_a_single_shallower_match_wins_over_deeper_sibling_matches(tmp_path):
    # Only the shallowest depth's matches are candidates — a single match
    # there is unambiguous even if more projects exist further down.
    (tmp_path / "app" / "pyproject.toml").parent.mkdir(parents=True)
    (tmp_path / "app" / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    nested_a = tmp_path / "app" / "vendor" / "a"
    nested_a.mkdir(parents=True)
    _write_package_json(nested_a, {"build": "vite build"})
    nested_b = tmp_path / "app" / "vendor" / "b"
    nested_b.mkdir(parents=True)
    _write_package_json(nested_b, {"build": "vite build"})

    detection = detect_project(str(tmp_path))

    assert detection == ProjectDetection(language="python", root=str(tmp_path / "app"))


# --- Stage 2: verification-plan discovery (pure, no subprocess) ------------


def _python_plan_for(tmp_path, state):
    return discover_verification_plan(
        ProjectDetection(language="python", root=str(tmp_path)), python_env=state
    )


def test_python_plan_has_pytest_as_the_only_primary_check(tmp_path):
    plan = _python_plan_for(tmp_path, _state(tmp_path))

    assert [s.name for s in plan] == ["pytest"]
    assert plan[0].primary is True
    assert plan[0].command == [sys.executable, "-m", "pytest", "-q"]
    assert plan[0].env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert plan[0].env["PATH"].startswith(f"{tmp_path / '.venv'}/bin:")


def test_python_plan_adds_ruff_when_configured_and_in_the_project_env(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")

    plan = _python_plan_for(tmp_path, _state(tmp_path, ("pytest", "ruff")))

    ruff_spec = next(s for s in plan if s.name == "ruff")
    assert ruff_spec.primary is False
    assert ruff_spec.command == [sys.executable, "-m", "ruff", "check", "."]


def test_python_plan_marks_ruff_unavailable_when_not_in_the_project_env(tmp_path):
    # ruff on PATH (or in Certo's own environment) doesn't count: the check
    # must run with the project's interpreter.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")

    plan = _python_plan_for(tmp_path, _state(tmp_path))

    ruff_spec = next(s for s in plan if s.name == "ruff")
    assert ruff_spec.command is None
    assert "not installed in the project environment" in ruff_spec.unavailable_reason


def test_python_plan_marks_mypy_unavailable_when_not_in_the_project_env(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n")

    plan = _python_plan_for(tmp_path, _state(tmp_path))

    mypy_spec = next(s for s in plan if s.name == "mypy")
    assert mypy_spec.command is None
    assert "not installed in the project environment" in mypy_spec.unavailable_reason


def test_python_plan_has_no_lint_typecheck_when_unconfigured(tmp_path):
    plan = _python_plan_for(tmp_path, _state(tmp_path))

    assert [s.name for s in plan] == ["pytest"]


def test_python_plan_without_a_prepared_env_never_guesses_an_interpreter(tmp_path):
    (tmp_path / "app.py").write_text("if __name__ == '__main__':\n    pass\n")

    plan = _python_plan_for(tmp_path, None)

    assert plan[0].name == "pytest"
    assert plan[0].command is None
    assert plan[0].unavailable_reason
    assert not [s for s in plan if s.name.startswith("python ")]


def test_python_plan_pytest_missing_with_tests_is_unavailable_not_failed(tmp_path):
    state = _state(tmp_path, ())
    state.pytest_unavailable_reason = "installing it failed: no network"

    plan = _python_plan_for(tmp_path, state)

    assert plan[0].command is None
    assert plan[0].unavailable_reason == "installing it failed: no network"
    assert execute_check(plan[0]).status == "unavailable"


def test_python_plan_pytest_missing_without_tests_is_skipped(tmp_path):
    plan = _python_plan_for(tmp_path, _state(tmp_path, (), has_tests=False))

    assert execute_check(plan[0]).status == "skipped"


@pytest.mark.parametrize("language_files", [{"app.py": "print(1)\n"}, {"pyproject.toml": ""}])
def test_python_verification_commands_never_reference_certos_own_interpreter(
    tmp_path, project_venv, language_files
):
    project_venv(tmp_path)
    for name, text in language_files.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "main.py").write_text("if __name__ == '__main__':\n    pass\n")
    (tmp_path / "ruff.toml").write_text("")

    commands = []

    class RecordingRunner(LocalRunner):
        def run(self, command, **kwargs):
            commands.append(list(command))
            return super().run(command, **kwargs)

    run = run_full_verification(str(tmp_path), runner=RecordingRunner())

    assert run.commands
    for command in run.commands:
        assert sys.executable not in command
        assert os.path.join(sys.prefix, "bin") not in command
    scripts, executable = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    expected = os.path.join(str(tmp_path), ".venv", scripts, executable)
    assert commands
    assert all(os.path.normpath(command[0]) == expected for command in commands)


def test_node_plan_prefers_build_as_primary_over_test(tmp_path):
    _write_package_json(tmp_path, {"build": "vite build", "test": "vitest run"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    primary = next(s for s in plan if s.primary)
    assert primary.name == "npm run build"
    assert {s.name for s in plan} == {"npm run build", "npm test"}


def test_node_plan_uses_test_as_primary_when_no_build_script(tmp_path):
    _write_package_json(tmp_path, {"test": "vitest run"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].name == "npm test"
    assert plan[0].primary is True


def test_node_plan_includes_lint_and_typecheck_when_defined(tmp_path):
    _write_package_json(
        tmp_path,
        {"build": "vite build", "lint": "eslint .", "typecheck": "tsc --noEmit"},
    )

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert {s.name for s in plan} == {"npm run build", "npm run lint", "npm run typecheck"}


def test_node_plan_accepts_type_check_hyphenated_key(tmp_path):
    _write_package_json(tmp_path, {"build": "vite build", "type-check": "tsc --noEmit"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert "npm run type-check" in {s.name for s in plan}


def test_node_plan_ignores_placeholder_test_script(tmp_path):
    _write_package_json(
        tmp_path, {"build": "vite build", "test": 'echo "Error: no test specified" && exit 1'}
    )

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert [s.name for s in plan] == ["npm run build"]


def test_node_plan_is_unavailable_with_no_build_or_test_script(tmp_path):
    _write_package_json(tmp_path, {"start": "node index.js"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].command is None
    assert "no build or test script" in plan[0].unavailable_reason


def test_node_plan_marks_every_check_unavailable_when_npm_missing(tmp_path, monkeypatch):
    _write_package_json(tmp_path, {"build": "vite build", "lint": "eslint ."})
    monkeypatch.setattr("shutil.which", lambda _name: None)

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert all(s.command is None for s in plan)
    assert all("npm not found" in s.unavailable_reason for s in plan)


def test_go_plan_has_test_and_vet(tmp_path):
    plan = discover_verification_plan(ProjectDetection(language="go", root=str(tmp_path)))

    names = {s.name: s.primary for s in plan}
    assert names == {"go test": True, "go vet": False}


def test_go_plan_unavailable_without_go_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    plan = discover_verification_plan(ProjectDetection(language="go", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].command is None
    assert "not installed" in plan[0].unavailable_reason


def test_rust_plan_has_test_check_and_clippy(tmp_path):
    plan = discover_verification_plan(ProjectDetection(language="rust", root=str(tmp_path)))

    names = {s.name: s.primary for s in plan}
    assert names == {"cargo test": True, "cargo check": False, "cargo clippy": False}


def test_rust_plan_unavailable_without_cargo_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    plan = discover_verification_plan(ProjectDetection(language="rust", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].command is None
    assert "not installed" in plan[0].unavailable_reason


def test_java_maven_plan_prefers_wrapper_over_global_mvn(tmp_path, monkeypatch):
    wrapper = tmp_path / "mvnw"
    wrapper.write_text("#!/bin/sh\nexit 0\n")
    wrapper.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "mvn" else None)

    plan = discover_verification_plan(ProjectDetection(language="java-maven", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].command == [str(wrapper), "test"]


def test_java_maven_plan_falls_back_to_global_mvn_without_wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mvn" if name == "mvn" else None)

    plan = discover_verification_plan(ProjectDetection(language="java-maven", root=str(tmp_path)))

    assert plan[0].command == ["/usr/bin/mvn", "test"]


def test_java_maven_plan_unavailable_with_neither_wrapper_nor_mvn(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    plan = discover_verification_plan(ProjectDetection(language="java-maven", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].command is None
    assert "mvnw" in plan[0].unavailable_reason
    assert "mvn" in plan[0].unavailable_reason


def test_java_gradle_plan_prefers_wrapper_over_global_gradle(tmp_path, monkeypatch):
    wrapper = tmp_path / "gradlew"
    wrapper.write_text("#!/bin/sh\nexit 0\n")
    wrapper.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    plan = discover_verification_plan(ProjectDetection(language="java-gradle", root=str(tmp_path)))

    assert plan[0].command == [str(wrapper), "test"]


def test_unknown_project_plan_is_a_single_unavailable_check(tmp_path):
    plan = discover_verification_plan(ProjectDetection(language="unknown", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].primary is True
    assert plan[0].command is None
    assert "contains no files" in plan[0].unavailable_reason


def test_unknown_project_reason_names_the_files_that_exist(tmp_path):
    # Live-caught: a self-contained index.html game got "No known project
    # type ... detected", which read as if no code had been produced.
    (tmp_path / "index.html").write_text("<script>let x = 1;</script>")
    (tmp_path / "README.md").write_text("# Game")

    reason = discover_verification_plan(ProjectDetection(language="unknown", root=str(tmp_path)))[
        0
    ].unavailable_reason

    assert "README.md, index.html" in reason
    assert "package.json" in reason and "pyproject.toml" in reason
    assert "unverified, not failed" in reason
    assert "open the page in a browser" in reason


def test_unknown_project_reason_omits_web_hint_without_html(tmp_path):
    (tmp_path / "notes.txt").write_text("hi")

    reason = discover_verification_plan(ProjectDetection(language="unknown", root=str(tmp_path)))[
        0
    ].unavailable_reason

    assert "notes.txt" in reason
    assert "browser" not in reason


def test_unknown_project_reason_truncates_long_listings_and_skips_noise(tmp_path):
    for i in range(8):
        (tmp_path / f"f{i}.txt").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")
    (tmp_path / ".hidden").write_text("x")

    reason = discover_verification_plan(ProjectDetection(language="unknown", root=str(tmp_path)))[
        0
    ].unavailable_reason

    assert "(8 files in total)" in reason
    assert "dep.js" not in reason and ".hidden" not in reason


def test_ambiguous_project_plan_is_a_single_unavailable_check_naming_candidates(tmp_path):
    detection = ProjectDetection(
        language="ambiguous",
        root=str(tmp_path),
        candidates=(("node", str(tmp_path / "frontend")), ("python", str(tmp_path / "backend"))),
    )

    plan = discover_verification_plan(detection)

    assert len(plan) == 1
    assert plan[0].primary is True
    assert plan[0].command is None
    assert "ambiguous" in plan[0].unavailable_reason
    assert str(tmp_path / "frontend") in plan[0].unavailable_reason
    assert str(tmp_path / "backend") in plan[0].unavailable_reason


# --- Stage 3: command execution ---------------------------------------------


def test_execute_check_reports_passed(tmp_path):
    spec = CheckSpec(
        name="ok", primary=True, command=[sys.executable, "-c", "pass"], cwd=str(tmp_path)
    )

    outcome = execute_check(spec)

    assert outcome.status == "passed"
    assert outcome.exit_code == 0
    assert outcome.project_root == str(tmp_path)
    assert outcome.command == f"{sys.executable} -c pass"


def test_execute_check_reports_failed_with_exit_code_and_output(tmp_path):
    spec = CheckSpec(
        name="broken",
        primary=True,
        command=[sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)"],
        cwd=str(tmp_path),
    )

    outcome = execute_check(spec)

    assert outcome.status == "failed"
    assert outcome.exit_code == 3
    assert "boom" in outcome.output


def test_execute_check_reports_skipped_via_skip_exit_code(tmp_path):
    spec = CheckSpec(
        name="pytest",
        primary=True,
        command=[sys.executable, "-c", "import sys; sys.exit(5)"],
        cwd=str(tmp_path),
        skip_exit_codes=(5,),
        skip_reason="no tests collected",
    )

    outcome = execute_check(spec)

    assert outcome.status == "skipped"
    assert outcome.summary == "no tests collected"


def test_execute_check_reports_skipped_when_command_is_none_with_skip_reason(tmp_path):
    spec = CheckSpec(
        name="lint", primary=False, command=None, cwd=str(tmp_path), skip_reason="not configured"
    )

    outcome = execute_check(spec)

    assert outcome.status == "skipped"
    assert outcome.exit_code is None
    assert outcome.summary == "not configured"


def test_execute_check_reports_unavailable_when_command_is_none_with_reason(tmp_path):
    spec = CheckSpec(
        name="mypy",
        primary=False,
        command=None,
        cwd=str(tmp_path),
        unavailable_reason="not installed",
    )

    outcome = execute_check(spec)

    assert outcome.status == "unavailable"
    assert outcome.summary == "not installed"


def test_execute_check_reports_unavailable_when_the_binary_does_not_exist(tmp_path):
    spec = CheckSpec(name="ghost", primary=True, command=["/no/such/binary-xyz"], cwd=str(tmp_path))

    outcome = execute_check(spec)

    assert outcome.status == "unavailable"
    assert "could not be run" in outcome.summary


@pytest.mark.parametrize(
    "message",
    [
        "error: no such command: `clippy`",
        "error: 'cargo-clippy' is not installed for the toolchain 'stable-aarch64-apple-darwin'",
    ],
)
def test_a_missing_clippy_is_unavailable_not_failed(tmp_path, monkeypatch, message):
    # cargo exits 101 when the clippy component is missing; that's a gap in
    # the toolchain, not a lint failure in the project.
    clippy = next(
        s
        for s in discover_verification_plan(ProjectDetection(language="rust", root=str(tmp_path)))
        if s.name == "cargo clippy"
    )
    script = f"import sys; print({message!r}, file=sys.stderr); sys.exit(101)"
    spec = dataclasses.replace(clippy, command=[sys.executable, "-c", script])

    outcome = execute_check(spec)

    assert outcome.status == "unavailable"
    assert outcome.exit_code is None
    assert "rustup component add clippy" in outcome.summary
    run = VerificationRun(checks=[outcome])
    assert run.state != "failed"
    assert run.limitation_notes == [f"cargo clippy: {outcome.summary}"]


def test_a_real_clippy_finding_still_fails(tmp_path):
    clippy = next(
        s
        for s in discover_verification_plan(ProjectDetection(language="rust", root=str(tmp_path)))
        if s.name == "cargo clippy"
    )
    script = "import sys; print('error: this looks like a bug', file=sys.stderr); sys.exit(101)"
    spec = dataclasses.replace(clippy, command=[sys.executable, "-c", script])

    assert execute_check(spec).status == "failed"


def test_execute_check_reports_timed_out(tmp_path, monkeypatch):
    import subprocess

    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="sleep 999", timeout=kwargs.get("timeout", 1), output="partial output"
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    spec = CheckSpec(name="slow", primary=True, command=["sleep", "999"], cwd=str(tmp_path))

    outcome = execute_check(spec, timeout=1)

    assert outcome.status == "timed_out"
    assert outcome.exit_code is None
    assert "timeout" in outcome.summary
    assert "partial output" in outcome.output


def test_execute_check_returns_a_precomputed_outcome_without_running_anything(
    tmp_path, monkeypatch
):
    import subprocess

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("execute_check must not spawn a subprocess for a precomputed spec")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)
    precomputed = CheckOutcome(
        name="static",
        command="",
        primary=False,
        status="failed",
        exit_code=None,
        project_root=str(tmp_path),
        summary="static check failed",
        output="details",
    )
    spec = CheckSpec(
        name="static", primary=False, command=None, cwd=str(tmp_path), precomputed=precomputed
    )

    assert execute_check(spec) is precomputed


def test_execute_check_closes_stdin_so_a_reading_subprocess_fails_fast_instead_of_hanging(tmp_path):
    # Regression guard for the entry-point smoke-test check below: without
    # stdin=DEVNULL, a script that calls input() would inherit whatever
    # stdin this test process has, which can hang a check indefinitely
    # instead of failing fast.
    spec = CheckSpec(
        name="reads-stdin",
        primary=True,
        command=[sys.executable, "-c", "input()"],
        cwd=str(tmp_path),
    )

    outcome = execute_check(spec, timeout=10)

    assert outcome.status == "failed"  # EOFError on closed stdin, not a hang
    assert outcome.exit_code != 0


# --- Python entry-point checks: catches a bug pytest structurally cannot ---
#
# A passing test suite only proves the code works when *imported* — a
# function defined after a module's own `if __name__ == "__main__":` guard
# exists by the time anything imports the module (the whole file runs
# top-to-bottom, guard included, and __name__ != "__main__" on import so the
# guarded call to main() never happens), but does not exist yet when the
# script is actually run directly and immediately calls into that guard.


_ORDERING_BUG_SOURCE = (
    "def main():\n"
    "    print('start')\n"
    "    helper()\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
    "\n"
    "def helper():\n"
    "    print('should have run')\n"
)

_ORDERING_OK_SOURCE = (
    "def helper():\n"
    "    print('should have run')\n"
    "\n"
    "def main():\n"
    "    print('start')\n"
    "    helper()\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)


def test_is_main_guard_recognizes_the_standard_form(tmp_path):
    (tmp_path / "app.py").write_text("if __name__ == '__main__':\n    pass\n")
    entrypoints = _find_python_entrypoints(str(tmp_path))
    assert entrypoints == ["app.py"]


def test_find_python_entrypoints_ignores_files_without_a_guard(tmp_path):
    (tmp_path / "lib.py").write_text("def helper():\n    pass\n")
    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_ignores_files_that_do_not_parse(tmp_path):
    (tmp_path / "broken.py").write_text("def helper(:\n    pass\n")
    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_empty_directory(tmp_path):
    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_finds_a_nested_one(tmp_path):
    nested = tmp_path / "src" / "app"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("if __name__ == '__main__':\n    pass\n")

    entrypoints = _find_python_entrypoints(str(tmp_path))

    assert entrypoints == [os.path.join("src", "app", "main.py")]


def test_find_python_entrypoints_finds_both_root_and_nested(tmp_path):
    (tmp_path / "cli.py").write_text("if __name__ == '__main__':\n    pass\n")
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "main.py").write_text("if __name__ == '__main__':\n    pass\n")

    entrypoints = _find_python_entrypoints(str(tmp_path))

    assert entrypoints == sorted(["cli.py", os.path.join("src", "main.py")])


def test_find_python_entrypoints_skips_vendored_dependencies(tmp_path):
    vendored = tmp_path / "vendor" / "some_lib"
    vendored.mkdir(parents=True)
    (vendored / "__main__.py").write_text("if __name__ == '__main__':\n    pass\n")

    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_skips_node_modules_and_venv(tmp_path):
    for skipped in ("node_modules", ".venv", "venv", "__pycache__"):
        d = tmp_path / skipped / "pkg"
        d.mkdir(parents=True)
        (d / "cli.py").write_text("if __name__ == '__main__':\n    pass\n")

    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_skips_the_tests_directory(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_cli.py").write_text(
        "if __name__ == '__main__':\n    import unittest\n    unittest.main()\n"
    )

    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_skips_hidden_directories(tmp_path):
    hidden = tmp_path / ".git" / "hooks"
    hidden.mkdir(parents=True)
    (hidden / "pre-commit.py").write_text("if __name__ == '__main__':\n    pass\n")

    assert _find_python_entrypoints(str(tmp_path)) == []


def test_find_python_entrypoints_respects_the_max_scan_depth(tmp_path):
    deep = tmp_path
    for i in range(6):
        deep = deep / f"level{i}"
    deep.mkdir(parents=True)
    (deep / "buried.py").write_text("if __name__ == '__main__':\n    pass\n")

    assert _find_python_entrypoints(str(tmp_path)) == []


def test_entrypoint_ordering_spec_checks_a_nested_entrypoint(tmp_path):
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "main.py").write_text(_ORDERING_BUG_SOURCE)

    entrypoints = _find_python_entrypoints(str(tmp_path))
    spec = _entrypoint_ordering_spec(str(tmp_path), entrypoints)

    assert spec is not None
    assert spec.precomputed.status == "failed"
    assert "helper" in spec.precomputed.output


def test_python_plan_smoke_run_command_uses_the_relative_nested_path(tmp_path):
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "main.py").write_text("if __name__ == '__main__':\n    pass\n")

    specs = _python_plan(str(tmp_path), _state(tmp_path))

    smoke_specs = [s for s in specs if s.name.startswith("python ")]
    assert len(smoke_specs) == 1
    assert smoke_specs[0].command[-1] == os.path.join("src", "main.py")
    assert smoke_specs[0].cwd == str(tmp_path)


def test_python_plan_runs_a_package_main_as_a_module(tmp_path):
    package = tmp_path / "hanoi"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("def main():\n    return 0\n")
    (package / "__main__.py").write_text(
        "from hanoi.cli import main\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n"
    )

    plan = _python_plan(str(tmp_path), _state(tmp_path))
    check = next(s for s in plan if s.name == "python -m hanoi")

    assert check.command[-2:] == ["-m", "hanoi"]
    assert check.cwd == str(tmp_path)
    assert execute_check(check).status == "passed"


def test_python_plan_runs_a_package_module_with_a_guard_as_a_module(tmp_path):
    package = tmp_path / "tool"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("if __name__ == '__main__':\n    pass\n")

    plan = _python_plan(str(tmp_path), _state(tmp_path))

    assert "python -m tool.cli" in {s.name for s in plan}


def test_entrypoint_ordering_spec_is_none_without_any_entrypoint(tmp_path):
    assert _entrypoint_ordering_spec(str(tmp_path), []) is None


def test_entrypoint_ordering_spec_passes_when_guard_is_last(tmp_path):
    (tmp_path / "app.py").write_text(_ORDERING_OK_SOURCE)

    spec = _entrypoint_ordering_spec(str(tmp_path), ["app.py"])
    outcome = execute_check(spec)

    assert outcome.status == "passed"


def test_entrypoint_ordering_spec_fails_when_something_is_defined_after_the_guard(tmp_path):
    # This is the exact live bug: `helper` (standing in for the real
    # project's `solve`) is defined after `if __name__ == "__main__":
    # main()`, and `main` calls it.
    (tmp_path / "app.py").write_text(_ORDERING_BUG_SOURCE)

    spec = _entrypoint_ordering_spec(str(tmp_path), ["app.py"])
    outcome = execute_check(spec)

    assert outcome.status == "failed"
    assert "app.py" in outcome.output
    assert "helper" in outcome.output
    assert "not the file's last top-level statement" in outcome.output


def test_python_plan_adds_entrypoint_checks_when_a_guard_is_present(tmp_path):
    (tmp_path / "app.py").write_text(_ORDERING_OK_SOURCE)

    plan = _python_plan(str(tmp_path), _state(tmp_path))

    names = {s.name for s in plan}
    assert "entrypoint-ordering" in names
    assert "python app.py" in names
    entrypoint_check = next(s for s in plan if s.name == "python app.py")
    assert entrypoint_check.primary is False


def test_python_plan_has_no_entrypoint_checks_without_a_guard(tmp_path):
    # Preserves existing behavior for every pre-existing fixture in this
    # file (bare directories of test_*.py with no __main__ guard anywhere).
    (tmp_path / "test_fixture.py").write_text("def test_ok():\n    assert True\n")

    plan = _python_plan(str(tmp_path), _state(tmp_path))

    assert {s.name for s in plan} == {"pytest"}


def test_full_verification_catches_the_live_ordering_bug_even_though_pytest_passes(
    tmp_path, project_venv
):
    project_venv(tmp_path)
    # The exact shape of the live failure: a test suite that only imports
    # the module (and therefore never calls into the __main__ guard) passes
    # cleanly, while running the script directly would crash. Verification
    # must not report "verified" here.
    (tmp_path / "app.py").write_text(_ORDERING_BUG_SOURCE)
    (tmp_path / "test_app.py").write_text(
        "from app import main\n\ndef test_main_is_importable():\n    assert callable(main)\n"
    )

    run = run_full_verification(str(tmp_path))

    pytest_check = next(c for c in run.checks if c.name == "pytest")
    assert pytest_check.status == "passed"
    assert run.state == "failed"
    ordering_check = next(c for c in run.checks if c.name == "entrypoint-ordering")
    assert ordering_check.status == "failed"


def test_full_verification_passes_when_entrypoint_ordering_is_correct(tmp_path, project_venv):
    project_venv(tmp_path)
    (tmp_path / "app.py").write_text(_ORDERING_OK_SOURCE)
    (tmp_path / "test_app.py").write_text(
        "from app import main\n\ndef test_main_is_importable():\n    assert callable(main)\n"
    )

    run = run_full_verification(str(tmp_path))

    assert run.state == "verified"


def test_entrypoint_smoke_check_fails_on_a_real_startup_crash(tmp_path):
    # A script that crashes immediately on an uncaught exception — nothing
    # to do with the ordering bug, a plain startup-crash check.
    (tmp_path / "app.py").write_text("if __name__ == '__main__':\n    raise RuntimeError('boom')\n")

    plan = _python_plan(str(tmp_path), _state(tmp_path))
    entrypoint_check = next(s for s in plan if s.name == "python app.py")
    outcome = execute_check(entrypoint_check)

    assert outcome.status == "failed"
    assert "boom" in outcome.output


# --- Stage 4: structured results / aggregation ------------------------------


def _check(
    name="pytest", command="pytest -q", *, primary=True, status="passed", exit_code=0, output=""
) -> CheckOutcome:
    return CheckOutcome(
        name=name,
        command=command,
        primary=primary,
        status=status,
        exit_code=exit_code,
        project_root="/tmp/x",
        summary="",
        output=output,
    )


def test_verification_run_is_verified_when_primary_passes():
    run = VerificationRun(checks=[_check(status="passed")])
    assert run.state == "verified"
    assert run.failing == []


def test_verification_run_is_failed_when_primary_fails():
    run = VerificationRun(checks=[_check(status="failed")])
    assert run.state == "failed"
    assert run.failing == run.checks


def test_verification_run_mixed_checks_one_passes_one_fails():
    # A configured lint/typecheck failure must block "verified" even though
    # the primary test/build check passed — never report success while a
    # configured check is genuinely failing.
    run = VerificationRun(
        checks=[
            _check(status="passed"),
            _check(name="ruff", command="ruff check .", primary=False, status="failed"),
        ]
    )
    assert run.state == "failed"
    assert [c.name for c in run.failing] == ["ruff"]


def test_verification_run_is_inconclusive_when_primary_skipped():
    run = VerificationRun(checks=[_check(status="skipped", exit_code=5)])
    assert run.state == "inconclusive"


def test_verification_run_is_inconclusive_when_primary_unavailable():
    run = VerificationRun(checks=[_check(status="unavailable", exit_code=None)])
    assert run.state == "inconclusive"


def test_verification_run_is_inconclusive_when_empty():
    assert VerificationRun(checks=[]).state == "inconclusive"


def test_verification_run_secondary_skip_does_not_block_verified():
    run = VerificationRun(
        checks=[
            _check(status="passed"),
            _check(name="mypy", command="mypy .", primary=False, status="unavailable"),
        ]
    )
    assert run.state == "verified"
    assert run.limitation_notes == ["mypy: "]


def test_verification_run_timed_out_is_distinct_from_failed():
    run = VerificationRun(checks=[_check(status="timed_out", exit_code=None)])
    assert run.state == "timed_out"
    assert run.timed_out_checks == run.checks
    assert run.failing == []


def test_verification_run_failed_takes_priority_over_timed_out():
    run = VerificationRun(
        checks=[
            _check(status="timed_out", exit_code=None),
            _check(name="ruff", primary=False, status="failed"),
        ]
    )
    assert run.state == "failed"


def test_verification_run_skipped_checks_are_not_limitations():
    run = VerificationRun(
        checks=[_check(status="passed"), _check(name="ruff", primary=False, status="skipped")]
    )
    assert run.limitation_notes == []


def test_verification_run_commands_omits_unavailable_empty_commands():
    run = VerificationRun(
        checks=[
            _check(command="pytest -q"),
            _check(name="mypy", command="", primary=False, status="unavailable"),
        ]
    )
    assert run.commands == ["pytest -q"]


# --- Full pipeline: run_full_verification -----------------------------------


def test_full_verification_python_project_with_passing_tests(tmp_path, project_venv):
    project_venv(tmp_path)
    (tmp_path / "test_fixture.py").write_text("def test_ok():\n    assert True\n")

    run = run_full_verification(str(tmp_path))

    assert run.state == "verified"
    assert [c.name for c in run.checks] == ["pytest"]


def test_full_verification_python_project_with_failing_tests(tmp_path, project_venv):
    project_venv(tmp_path)
    _write_fixture(tmp_path)

    run = run_full_verification(str(tmp_path))

    assert run.state == "failed"


def test_full_verification_no_test_python_project_is_inconclusive(tmp_path, project_venv):
    project_venv(tmp_path)
    # A recognized Python project (has actual .py source) with no tests
    # defined yet — inconclusive, not a failure, per the pytest exit-5
    # exemption.
    (tmp_path / "main.py").write_text("print('hello')\n")

    run = run_full_verification(str(tmp_path))

    assert run.state == "inconclusive"
    assert run.checks[0].status == "skipped"


def test_full_verification_unknown_project_is_inconclusive_and_unavailable(tmp_path):
    (tmp_path / "README.md").write_text("nothing recognizable here\n")

    run = run_full_verification(str(tmp_path))

    assert run.state == "inconclusive"
    assert run.checks[0].status == "unavailable"
    assert run.limitation_notes


def test_full_verification_monorepo_with_sibling_projects_is_inconclusive_and_unavailable(
    tmp_path,
):
    # A workspace containing two unrelated applications with no manifest of
    # its own — full pipeline must not silently verify just one of them.
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _write_package_json(frontend, {"build": "vite build"})
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[project]\nname = 'backend'\n")

    run = run_full_verification(str(tmp_path))

    assert run.state == "inconclusive"
    assert run.checks[0].status == "unavailable"
    assert "ambiguous" in run.limitation_notes[0]
    assert str(frontend) in run.limitation_notes[0]
    assert str(backend) in run.limitation_notes[0]


def test_full_verification_runs_ruff_when_configured_and_available(tmp_path, project_venv):
    project_venv(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "test_fixture.py").write_text("def test_ok():\n    assert True\n")
    # An unused import is a real ruff violation (F401) — deterministic, no
    # network, doesn't depend on any project-specific ruff config beyond the
    # bare [tool.ruff] section above.
    (tmp_path / "bad.py").write_text("import os\n")

    run = run_full_verification(str(tmp_path))

    assert {c.name for c in run.checks} == {"pytest", "ruff"}
    assert run.state == "failed"
    ruff_check = next(c for c in run.checks if c.name == "ruff")
    assert ruff_check.status == "failed"


@_requires_npm
def test_full_verification_node_project_build_only(tmp_path):
    _write_package_json(tmp_path, {"build": 'node -e "process.exit(0)"'})

    run = run_full_verification(str(tmp_path))

    assert [c.name for c in run.checks] == ["npm run build"]
    assert run.state == "verified"


@_requires_npm
def test_full_verification_node_project_test_script_failure_fails_overall(tmp_path):
    _write_package_json(
        tmp_path,
        {"build": 'node -e "process.exit(0)"', "test": 'node -e "process.exit(1)"'},
    )

    run = run_full_verification(str(tmp_path))

    assert run.state == "failed"
    test_check = next(c for c in run.checks if c.name == "npm test")
    assert test_check.status == "failed"


@_requires_go
def test_full_verification_go_project_real_pass(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/fixture\n\ngo 1.21\n")
    (tmp_path / "fixture_test.go").write_text(
        'package fixture\n\nimport "testing"\n\nfunc TestOK(t *testing.T) {}\n'
    )

    run = run_full_verification(str(tmp_path))

    assert run.state == "verified"
    assert {c.name for c in run.checks} == {"go test", "go vet"}
    assert all(c.status == "passed" for c in run.checks)


@_requires_go
def test_full_verification_go_project_real_failure(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/fixture\n\ngo 1.21\n")
    (tmp_path / "fixture_test.go").write_text(
        'package fixture\n\nimport "testing"\n\nfunc TestFails(t *testing.T) { t.Fatal("boom") }\n'
    )

    run = run_full_verification(str(tmp_path))

    assert run.state == "failed"
    test_check = next(c for c in run.checks if c.name == "go test")
    assert test_check.status == "failed"
    assert "boom" in test_check.output


@_requires_cargo
def test_full_verification_rust_project_real_pass(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "fixture"\nversion = "0.1.0"\nedition = "2021"\n'
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n"
        "#[cfg(test)]\nmod tests {\n"
        "    use super::*;\n"
        "    #[test]\n"
        "    fn it_adds() { assert_eq!(add(2, 2), 4); }\n"
        "}\n"
    )

    run = run_full_verification(str(tmp_path))

    assert run.state == "verified"
    assert {c.name for c in run.checks} == {"cargo test", "cargo check", "cargo clippy"}


@pytest.mark.skipif(shutil.which("mvn") is not None, reason="mvn installed (e.g. CI runners)")
def test_full_verification_java_maven_project_reports_unavailable(tmp_path):
    # mvn/mvnw genuinely aren't installed in this dev environment — a real
    # exercise of the "configured but no toolchain" path, same pattern as
    # the mypy test above.
    (tmp_path / "pom.xml").write_text("<project></project>\n")

    run = run_full_verification(str(tmp_path))

    assert shutil.which("mvn") is None  # confirms the test exercises the real gap
    assert run.state == "inconclusive"
    assert run.checks[0].status == "unavailable"


def test_full_verification_java_maven_with_fake_wrapper_can_pass(tmp_path):
    # Exercises the "verified" path for Java without needing a real Maven
    # installation: a wrapper script that always exits 0 stands in for it.
    wrapper = tmp_path / "mvnw"
    wrapper.write_text("#!/bin/sh\nexit 0\n")
    wrapper.chmod(0o755)
    (tmp_path / "pom.xml").write_text("<project></project>\n")

    run = run_full_verification(str(tmp_path))

    assert run.state == "verified"
    assert run.checks[0].name == "mvn test"


# --- Legacy detection helpers used by plan discovery ------------------------


def test_ruff_not_configured_by_default(tmp_path):
    assert _ruff_configured(str(tmp_path)) is False


def test_ruff_configured_via_pyproject_tool_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert _ruff_configured(str(tmp_path)) is True


def test_ruff_configured_via_standalone_toml_file(tmp_path):
    (tmp_path / "ruff.toml").write_text("line-length = 100\n")
    assert _ruff_configured(str(tmp_path)) is True


def test_mypy_not_configured_by_default(tmp_path):
    assert _mypy_configured(str(tmp_path)) is False


def test_mypy_configured_via_pyproject_tool_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.mypy]\nstrict = true\n")
    assert _mypy_configured(str(tmp_path)) is True


def test_mypy_configured_via_ini_file(tmp_path):
    (tmp_path / "mypy.ini").write_text("[mypy]\nstrict = True\n")
    assert _mypy_configured(str(tmp_path)) is True


def test_malformed_pyproject_toml_does_not_crash_detection(tmp_path):
    (tmp_path / "pyproject.toml").write_text("this is not [ valid toml")
    assert _ruff_configured(str(tmp_path)) is False
    assert _mypy_configured(str(tmp_path)) is False


def test_npm_test_script_returns_a_real_script(tmp_path):
    _write_package_json(tmp_path, {"test": "vitest run"})
    assert _npm_test_script(str(tmp_path)) == "vitest run"


def test_npm_test_script_ignores_the_default_placeholder(tmp_path):
    _write_package_json(tmp_path, {"test": 'echo "Error: no test specified" && exit 1'})
    assert _npm_test_script(str(tmp_path)) is None


def test_npm_test_script_is_none_when_undefined(tmp_path):
    _write_package_json(tmp_path, {"build": "vite build"})
    assert _npm_test_script(str(tmp_path)) is None


def test_npm_test_script_is_none_without_package_json(tmp_path):
    assert _npm_test_script(str(tmp_path)) is None


# --- successful runs that did nothing (node --test, issue #23) -------------


def test_execute_check_reports_skipped_on_a_successful_no_work_run(tmp_path):
    spec = CheckSpec(
        name="npm test",
        primary=True,
        command=[sys.executable, "-c", "print('# tests 0'); import sys; sys.exit(0)"],
        cwd=str(tmp_path),
        no_work_markers=("tests 0",),
        no_work_reason="no tests ran (node --test found no test files)",
    )

    outcome = execute_check(spec)

    assert outcome.status == "skipped"
    assert outcome.exit_code == 0
    assert outcome.primary is True
    assert outcome.summary == "no tests ran (node --test found no test files)"
    assert "# tests 0" in outcome.output


def test_execute_check_matches_the_spec_reporter_summary(tmp_path):
    """Node 22+/26 prints '\u2139 tests 0' even through a pipe, not only TAP's '# tests 0'."""
    spec = CheckSpec(
        name="npm test",
        primary=True,
        command=[sys.executable, "-c", "print('\u2139 tests 0'); import sys; sys.exit(0)"],
        cwd=str(tmp_path),
        no_work_markers=("tests 0",),
        no_work_reason="no tests ran (node --test found no test files)",
    )

    outcome = execute_check(spec)

    assert outcome.status == "skipped"


def test_execute_check_keeps_a_real_pass_without_the_marker(tmp_path):
    spec = CheckSpec(
        name="npm test",
        primary=True,
        command=[sys.executable, "-c", "print('# tests 4'); import sys; sys.exit(0)"],
        cwd=str(tmp_path),
        no_work_markers=("tests 0",),
    )

    outcome = execute_check(spec)

    assert outcome.status == "passed"


def test_no_work_marker_never_downgrades_a_failing_run(tmp_path):
    spec = CheckSpec(
        name="npm test",
        primary=True,
        command=[sys.executable, "-c", "print('# tests 0'); import sys; sys.exit(1)"],
        cwd=str(tmp_path),
        no_work_markers=("tests 0",),
    )

    outcome = execute_check(spec)

    assert outcome.status == "failed"


def test_node_plan_primary_test_spec_detects_a_zero_test_run(tmp_path):
    _write_package_json(tmp_path, {"test": "node --test"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    assert len(plan) == 1
    assert plan[0].name == "npm test"
    assert plan[0].primary is True
    assert plan[0].no_work_markers == ("tests 0",)
    assert plan[0].no_work_reason == "no tests ran (node --test found no test files)"


def test_node_plan_extra_test_check_is_left_alone(tmp_path):
    _write_package_json(tmp_path, {"build": "vite build", "test": "node --test"})

    plan = discover_verification_plan(ProjectDetection(language="node", root=str(tmp_path)))

    by_name = {spec.name: spec for spec in plan}
    assert set(by_name) == {"npm run build", "npm test"}
    # An extra check can only turn a pass into a failure, so its outcome is
    # deliberately unchanged here (issue #23).
    assert by_name["npm run build"].primary is True
    assert by_name["npm run build"].no_work_markers == ()
    assert by_name["npm test"].primary is False
    assert by_name["npm test"].no_work_markers == ()


def test_zero_test_primary_check_ends_inconclusive_not_verified():
    primary = CheckOutcome(
        name="npm test",
        command="npm test",
        primary=True,
        status="skipped",
        exit_code=0,
        project_root=".",
        summary="no tests ran (node --test found no test files)",
        output="# tests 0",
    )
    run = VerificationRun(checks=[primary])

    assert run.state == "inconclusive"
