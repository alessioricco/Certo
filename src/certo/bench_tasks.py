"""The benchmark's task set: load tasks, prepare a run's workspace, and grade
a finished workspace with the task's hidden tests.

A task is a folder:

    <name>/task.md        the prompt the agent sees
    <name>/starter/       optional starting files the agent sees
    <name>/hidden_tests/  the tests that decide the score; never shown to the agent
    <name>/reference/     a reference solution; never shown to the agent

The hidden tests' language is the task's language:

- `.py`: pytest, in the project's own environment;
- `.js`: `node --test`, after `npm ci` (or `npm install` without a lock
  file) when `package.json` declares packages;
- `_test.go`: `go test` on the hidden tests' folder, a package of its own
  inside the module that imports the project's packages by their path;
- `.rs`: Cargo integration tests, copied into `tests/` as
  `certo_hidden_<name>.rs` (Cargo finds test targets only there) and run
  with `cargo test --test`. They see the library's public API and, for a
  binary, `CARGO_BIN_EXE_<name>`.

Only the hidden tests run: the agent's own tests can't change the score.
`run_test_folder()` runs any folder of tests the same way, for the
independent tests a run can have (DECISIONS.md).

The bundled set lives in `benchmark_tasks/` inside the package, like the
built-in skills. No SDK import here: loading, preparing and grading are all
testable without a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from .project_env import (
    CommandRunner,
    LocalRunner,
    available_modules,
    ensure_project_env,
    install_into_env,
)

BUILTIN_TASKS_DIR = Path(__file__).resolve().parent / "benchmark_tasks"
# Where grading copies the hidden tests in a finished workspace. A dot
# folder, so project detection and entry-point discovery never see it.
HIDDEN_DIR_NAME = ".certo_hidden_tests"
# Rust hidden tests go into the project's tests/ folder under this prefix.
RUST_HIDDEN_PREFIX = "certo_hidden_"
GRADE_TIMEOUT_SECONDS = 300
_OUTPUT_TAIL = 4000


class BenchTaskError(ValueError):
    """A task folder that doesn't have the required shape."""


@dataclass(frozen=True)
class BenchTask:
    name: str
    path: Path
    language: str  # one of LANGUAGES

    @property
    def prompt(self) -> str:
        return (self.path / "task.md").read_text(encoding="utf-8")

    @property
    def starter_dir(self) -> Path:
        return self.path / "starter"

    @property
    def hidden_dir(self) -> Path:
        return self.path / "hidden_tests"

    @property
    def reference_dir(self) -> Path:
        return self.path / "reference"


# A task's language, from its hidden test files' names, in this order.
_TEST_SUFFIXES = {"python": ".py", "node": ".js", "go": "_test.go", "rust": ".rs"}
LANGUAGES = tuple(_TEST_SUFFIXES)


def test_language(tests_dir: Path) -> str | None:
    """The language of the test files in `tests_dir`, from their names, or
    None when it holds none Certo can run."""
    names = [p.name for p in tests_dir.iterdir() if p.is_file()] if tests_dir.is_dir() else []
    for language, suffix in _TEST_SUFFIXES.items():
        if any(n.endswith(suffix) for n in names):
            return language
    return None


def _language(hidden: Path) -> str:
    language = test_language(hidden)
    if language is None:
        raise BenchTaskError(f"{hidden} has no .py, .js, _test.go or .rs test files")
    return language


def load_task(path: Path) -> BenchTask:
    if not (path / "task.md").is_file():
        raise BenchTaskError(f"{path} has no task.md")
    hidden = path / "hidden_tests"
    if not hidden.is_dir():
        raise BenchTaskError(f"{path} has no hidden_tests/ folder")
    return BenchTask(name=path.name, path=path, language=_language(hidden))


def load_tasks(tasks_dir: Path | str = BUILTIN_TASKS_DIR) -> list[BenchTask]:
    """Every task folder under `tasks_dir` (a folder with a task.md), by name."""
    root = Path(tasks_dir)
    if not root.is_dir():
        raise BenchTaskError(f"task folder not found: {root}")
    return [
        load_task(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")
    ]


def task_set_version(tasks_dir: Path | str = BUILTIN_TASKS_DIR) -> str:
    """The `VERSION` file of a task set, or "custom" when it has none."""
    version_file = Path(tasks_dir) / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "custom"


def task_set_hash(tasks_dir: Path | str = BUILTIN_TASKS_DIR) -> str:
    """A short hash of every file in the task set, so results from two
    machines can be checked to use exactly the same tasks."""
    root = Path(tasks_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.name == ".DS_Store":
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def copy_fresh(source: Path | str, target: Path | str, **kwargs) -> None:
    """`shutil.copytree`, but each copied file gets the time of the copy.

    Benchmark folders live in the system's temporary folder, and macOS
    deletes files there that look older than 3 days (`dirhelper`, every
    night at 03:35). A copy that kept the task file's own date was deleted
    mid-run: a starter `package.json` the agent never edited vanished, and
    the run was left with nothing Certo could check."""
    shutil.copytree(source, target, copy_function=shutil.copy, **kwargs)


def _copy_into(source: Path, target: Path) -> None:
    if source.is_dir():
        copy_fresh(source, target, dirs_exist_ok=True)


def prepare_workspace(task: BenchTask, workspace: Path | str, *, solved: bool = False) -> None:
    """Fill `workspace` with the starter files, which is all the agent sees.
    `solved=True` adds the reference solution on top (task validation only)."""
    target = Path(workspace)
    target.mkdir(parents=True, exist_ok=True)
    _copy_into(task.starter_dir, target)
    if solved:
        _copy_into(task.reference_dir, target)


@dataclass(frozen=True)
class GradeResult:
    status: str  # "passed" | "failed" | "error" (couldn't grade at all)
    summary: str
    command: str = ""
    output: str = ""
    # Python tasks whose hidden tests are named `test_mN_...` (a task in
    # milestones): milestone number -> (passed, total). None otherwise.
    by_milestone: dict[int, tuple[int, int]] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _copy_hidden_tests(tests_dir: Path, language: str, workspace: Path) -> list[str]:
    hidden = workspace / HIDDEN_DIR_NAME
    if hidden.exists():
        shutil.rmtree(hidden)
    copy_fresh(tests_dir, hidden)
    suffix = _TEST_SUFFIXES[language]
    return sorted(str(p) for p in hidden.iterdir() if p.is_file() and p.name.endswith(suffix))


def _grade_python(tests_dir: Path, workspace: Path, runner: CommandRunner) -> GradeResult:
    setup = ensure_project_env(str(workspace), runner, stop_at=str(workspace))
    if setup.env is None:
        return GradeResult("error", f"no project environment: {setup.unavailable_reason}")
    env = setup.env
    modules = available_modules(env, runner, str(workspace))
    if modules is None:
        return GradeResult("error", "the project environment's interpreter could not be run")
    if "pytest" not in modules:
        install = install_into_env(env, runner, "pytest", str(workspace))
        if install.returncode != 0:
            detail = _last_line(install.error or install.output) or "install failed"
            return GradeResult("error", f"could not install pytest for grading: {detail}")
    files = _copy_hidden_tests(tests_dir, "python", workspace)
    hidden = workspace / HIDDEN_DIR_NAME
    # An ini file of our own: the project's pytest settings (addopts, plugins)
    # must not change how the hidden tests run.
    ini = hidden / "pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    command = [
        *env.python,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        # One test file that can't import (a module the work never wrote)
        # must not hide the others' results.
        "--continue-on-collection-errors",
        # Every test's outcome on its own line, for the count per milestone.
        "-rA",
        "-c",
        str(ini),
        "--rootdir",
        str(hidden),
        *files,
    ]
    extra = {
        **env.env_vars(runner.base_path()),
        "PYTHONPATH": str(workspace),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = runner.run(command, cwd=str(workspace), env=extra, timeout=GRADE_TIMEOUT_SECONDS)
    graded = _result(command, result, failed_codes=(1, 2))
    return replace(graded, by_milestone=milestone_counts(result.output or ""))


def _declares_packages(workspace: Path) -> bool:
    try:
        manifest = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and bool(
        manifest.get("dependencies") or manifest.get("devDependencies")
    )


def _install_node_packages(workspace: Path, runner: CommandRunner) -> GradeResult | None:
    """Install the packages `package.json` declares; a GradeResult only when
    that fails. `npm ci` with a lock file, so grading uses exactly it, and
    never a package's install scripts: grading needs its files only."""
    if not _declares_packages(workspace):
        return None
    npm = runner.which("npm")
    if npm is None:
        return GradeResult("error", "npm is not installed")
    action = "ci" if (workspace / "package-lock.json").is_file() else "install"
    command = [npm, action, "--ignore-scripts", "--no-audit", "--no-fund"]
    result = runner.run(command, cwd=str(workspace), timeout=GRADE_TIMEOUT_SECONDS)
    if result.returncode == 0 and not result.timed_out:
        return None
    detail = (
        f"timed out after {GRADE_TIMEOUT_SECONDS}s"
        if result.timed_out
        else _last_line(result.error or result.output) or f"exit {result.returncode}"
    )
    return GradeResult(
        "error",
        f"could not install the project's packages for grading: {detail}",
        " ".join(command),
        result.output[-_OUTPUT_TAIL:],
    )


def _grade_node(tests_dir: Path, workspace: Path, runner: CommandRunner) -> GradeResult:
    node = runner.which("node")
    if node is None:
        return GradeResult("error", "node is not installed")
    failed_install = _install_node_packages(workspace, runner)
    if failed_install is not None:
        return failed_install
    files = _copy_hidden_tests(tests_dir, "node", workspace)
    command = [node, "--test", *files]
    result = runner.run(command, cwd=str(workspace), timeout=GRADE_TIMEOUT_SECONDS)
    return _result(command, result, failed_codes=None)


def _grade_go(tests_dir: Path, workspace: Path, runner: CommandRunner) -> GradeResult:
    go = runner.which("go")
    if go is None:
        return GradeResult("error", "go is not installed")
    if not (workspace / "go.mod").is_file():
        return GradeResult("failed", "no go.mod: the project isn't a Go module")
    _copy_hidden_tests(tests_dir, "go", workspace)
    # An explicit path: `./...` skips dot folders. -count=1: never a cached result.
    command = [go, "test", "-v", "-count=1", f"./{HIDDEN_DIR_NAME}"]
    result = runner.run(command, cwd=str(workspace), timeout=GRADE_TIMEOUT_SECONDS)
    return _result(command, result, failed_codes=None)


def _grade_rust(tests_dir: Path, workspace: Path, runner: CommandRunner) -> GradeResult:
    cargo = runner.which("cargo")
    if cargo is None:
        return GradeResult("error", "cargo is not installed")
    if not (workspace / "Cargo.toml").is_file():
        return GradeResult("failed", "no Cargo.toml: the project isn't a Cargo package")
    tests = workspace / "tests"
    tests.mkdir(exist_ok=True)
    for old in tests.glob(f"{RUST_HIDDEN_PREFIX}*.rs"):
        old.unlink()
    targets = []
    for source in sorted(tests_dir.glob("*.rs")):
        target = RUST_HIDDEN_PREFIX + source.stem
        shutil.copyfile(source, tests / f"{target}.rs")
        targets += ["--test", target]
    command = [cargo, "test", *targets]
    result = runner.run(command, cwd=str(workspace), timeout=GRADE_TIMEOUT_SECONDS)
    return _result(command, result, failed_codes=None)


def _result(command, result, *, failed_codes) -> GradeResult:
    shown = " ".join(command)
    output = result.output[-_OUTPUT_TAIL:]
    if result.timed_out:
        return GradeResult("failed", f"timed out after {GRADE_TIMEOUT_SECONDS}s", shown, output)
    if result.returncode is None:
        return GradeResult("error", f"could not run: {result.error}", shown, output)
    # Counted on the whole output: `go test -v` lists every test.
    if result.returncode == 0:
        if _counts(result.output) == (0, 0):
            return GradeResult("error", "no tests ran", shown, output)
        return GradeResult("passed", _summary(result.output), shown, output)
    if failed_codes is None or result.returncode in failed_codes:
        return GradeResult("failed", _summary(result.output), shown, output)
    return GradeResult("error", f"exit {result.returncode}: {_last_line(output)}", shown, output)


_CARGO_RESULT = re.compile(r"test result: \w+\. (\d+) passed; (\d+) failed")


def _counts(output: str) -> tuple[int, int] | None:
    """(passed, failed) from node's '# pass N' / '# fail N', `cargo test`'s
    result lines or `go test -v`'s; None for pytest, whose last line says it."""
    lines = [line.strip() for line in output.splitlines()]
    node = {
        line.split()[1]: int(line.split()[2])
        for line in lines
        if re.fullmatch(r"# (pass|fail) \d+", line)
    }
    if node:
        return node.get("pass", 0), node.get("fail", 0)
    cargo = _CARGO_RESULT.findall(output)
    if cargo:
        return sum(int(p) for p, _ in cargo), sum(int(f) for _, f in cargo)
    go_pass = sum(line.startswith("--- PASS") for line in lines)
    go_fail = sum(line.startswith("--- FAIL") for line in lines)
    if go_pass or go_fail or "[no test files]" in output or "no tests to run" in output:
        return go_pass, go_fail
    return None


# `-rA` lines of a test named for its milestone: "PASSED path::test_m3_..."
_MILESTONE_TEST = re.compile(r"^(PASSED|FAILED|ERROR) \S+::test_m(\d+)_", re.MULTILINE)


def milestone_counts(output: str) -> dict[int, tuple[int, int]] | None:
    """Passed and total hidden tests per milestone, from pytest's `-rA`
    report, for tests named `test_mN_...`; None when no test is."""
    counts: dict[int, list[int]] = {}
    for outcome, number in _MILESTONE_TEST.findall(output):
        passed_total = counts.setdefault(int(number), [0, 0])
        passed_total[1] += 1
        if outcome == "PASSED":
            passed_total[0] += 1
    if not counts:
        return None
    return {n: (p, t) for n, (p, t) in sorted(counts.items())}


def _summary(output: str) -> str:
    counts = _counts(output)
    return f"pass {counts[0]}, fail {counts[1]}" if counts else _last_line(output)


_GRADERS = {
    "python": _grade_python,
    "node": _grade_node,
    "go": _grade_go,
    "rust": _grade_rust,
}


def run_test_folder(
    tests_dir: Path | str,
    workspace: Path | str,
    runner: CommandRunner | None = None,
    *,
    language: str | None = None,
    clean_up: bool = False,
) -> GradeResult:
    """Copy the tests in `tests_dir` into `workspace` and run only them, in
    the project's own environment. `language` defaults to the test files'
    own (`test_language`). `clean_up` removes the copies afterwards, so the
    project is left as it was (the hidden-test folder, Rust's copies in
    `tests/`); Python's environment and Node's packages stay."""
    tests_dir = Path(tests_dir)
    root = Path(os.path.abspath(workspace))
    language = language or _language(tests_dir)
    try:
        return _GRADERS[language](tests_dir, root, runner or LocalRunner())
    finally:
        if clean_up:
            shutil.rmtree(root / HIDDEN_DIR_NAME, ignore_errors=True)
            for copy in (root / "tests").glob(f"{RUST_HIDDEN_PREFIX}*.rs"):
                copy.unlink()


def grade(
    task: BenchTask, workspace: Path | str, runner: CommandRunner | None = None
) -> GradeResult:
    """Copy the hidden tests into `workspace` and run them in the project's
    own environment. Only these tests decide the score."""
    return run_test_folder(task.hidden_dir, workspace, runner, language=task.language)
