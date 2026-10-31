"""The bundled benchmark tasks are valid: each reference solution passes its
hidden tests and the starter alone fails them. No model involved."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from certo import bench_tasks
from certo.bench_tasks import (
    BUILTIN_TASKS_DIR,
    BenchTaskError,
    grade,
    load_tasks,
    prepare_workspace,
)

TASKS = load_tasks()


def _workspace(tmp_path: Path, task, make_venv, *, solved: bool) -> Path:
    workspace = tmp_path / "ws"
    prepare_workspace(task, workspace, solved=solved)
    tool = {"python": None, "node": "node", "go": "go", "rust": "cargo"}[task.language]
    if tool is None:
        # Offline: a venv that already sees the test environment's pytest.
        make_venv(workspace)
    elif shutil.which(tool) is None:
        pytest.skip(f"{tool} is not installed")
    return workspace


def test_bundled_task_set_shape():
    assert TASKS
    for task in TASKS:
        assert task.language in bench_tasks.LANGUAGES, task.name
        assert task.prompt.strip(), task.name
        assert task.reference_dir.is_dir(), task.name


def test_hidden_tests_and_reference_are_not_in_the_starter():
    for task in TASKS:
        if not task.starter_dir.is_dir():
            continue
        starter = {p.name for p in task.starter_dir.rglob("*")}
        assert not starter & {p.name for p in task.hidden_dir.iterdir()}, task.name


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_reference_solution_passes_its_hidden_tests(task, tmp_path, project_venv):
    result = grade(task, _workspace(tmp_path, task, project_venv, solved=True))
    assert result.status == "passed", f"{task.name}: {result.summary}\n{result.output}"


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_starter_alone_fails_its_hidden_tests(task, tmp_path, project_venv):
    result = grade(task, _workspace(tmp_path, task, project_venv, solved=False))
    assert result.status == "failed", f"{task.name}: {result.summary}\n{result.output}"


def test_grading_ignores_the_projects_own_pytest_settings(tmp_path, project_venv):
    task = next(t for t in TASKS if t.name == "temperature-table")
    workspace = _workspace(tmp_path, task, project_venv, solved=True)
    (workspace / "pytest.ini").write_text("[pytest]\naddopts = --no-such-option\n")
    assert grade(task, workspace).passed


def test_a_task_with_no_collected_hidden_tests_is_an_error(tmp_path, project_venv):
    root = tmp_path / "tasks" / "empty-tests"
    (root / "hidden_tests").mkdir(parents=True)
    (root / "task.md").write_text("Do nothing.\n")
    (root / "hidden_tests" / "test_nothing.py").write_text("# no tests here\n")
    task = bench_tasks.load_task(root)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    project_venv(workspace)
    result = grade(task, workspace)
    assert result.status == "error"


def test_test_language_is_none_without_runnable_tests(tmp_path):
    assert bench_tasks.test_language(tmp_path / "missing") is None
    (tmp_path / "notes.txt").write_text("not a test")
    assert bench_tasks.test_language(tmp_path) is None
    (tmp_path / "test_x.py").write_text("")
    assert bench_tasks.test_language(tmp_path) == "python"


def test_a_test_folder_runs_and_can_leave_the_project_as_it_was(tmp_path, project_venv):
    tests = tmp_path / "tests-from-elsewhere"
    tests.mkdir()
    (tests / "test_add.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    project_venv(workspace)

    result = bench_tasks.run_test_folder(tests, workspace, clean_up=True)

    assert result.status == "passed", result.output
    assert not (workspace / bench_tasks.HIDDEN_DIR_NAME).exists()
    assert (workspace / "calc.py").exists()


def test_task_folders_must_have_the_required_shape(tmp_path):
    (tmp_path / "no-prompt" / "hidden_tests").mkdir(parents=True)
    with pytest.raises(BenchTaskError, match="task.md"):
        load_tasks(tmp_path)


def test_task_set_version_and_hash():
    assert bench_tasks.task_set_version() == (BUILTIN_TASKS_DIR / "VERSION").read_text().strip()
    assert bench_tasks.task_set_hash() == bench_tasks.task_set_hash()
    assert len(bench_tasks.task_set_hash()) == 12


def test_a_custom_task_set_without_version_is_custom(tmp_path):
    assert bench_tasks.task_set_version(tmp_path) == "custom"


# --- Go, Rust and Node with packages: small tasks built here, no network ---


def _task(tmp_path: Path, hidden: dict[str, str]) -> bench_tasks.BenchTask:
    root = tmp_path / "tasks" / "t"
    (root / "hidden_tests").mkdir(parents=True)
    (root / "task.md").write_text("Do it.\n")
    for name, text in hidden.items():
        (root / "hidden_tests" / name).write_text(text)
    return bench_tasks.load_task(root)


def _files(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


_GO_HIDDEN = """package hidden

import (
\t"testing"

\t"example.com/calc"
)

func TestAdd(t *testing.T) {
\tif calc.Add(2, 3) != 5 {
\t\tt.Fatal("Add(2, 3) != 5")
\t}
}
"""


def _go_project(root: Path, body: str) -> Path:
    return _files(
        root,
        {
            "go.mod": "module example.com/calc\n\ngo 1.21\n",
            "calc.go": f"package calc\n\nfunc Add(a, b int) int {{ {body} }}\n",
            # The agent's own failing test never counts.
            "calc_test.go": 'package calc\n\nimport "testing"\n\n'
            'func TestMine(t *testing.T) { t.Fatal("mine") }\n',
        },
    )


@pytest.mark.skipif(shutil.which("go") is None, reason="go is not installed")
def test_go_hidden_tests_decide_the_grade(tmp_path):
    task = _task(tmp_path, {"add_test.go": _GO_HIDDEN})
    assert task.language == "go"

    right = grade(task, _go_project(tmp_path / "right", "return a + b"))
    wrong = grade(task, _go_project(tmp_path / "wrong", "return a - b"))

    assert (right.status, right.summary) == ("passed", "pass 1, fail 0"), right.output
    assert (wrong.status, wrong.summary) == ("failed", "pass 0, fail 1"), wrong.output


@pytest.mark.skipif(shutil.which("go") is None, reason="go is not installed")
def test_go_hidden_tests_that_run_nothing_are_an_error(tmp_path):
    task = _task(tmp_path, {"add_test.go": "package hidden\n"})

    assert grade(task, _go_project(tmp_path / "ws", "return a + b")).status == "error"


_RUST_HIDDEN = """#[test]
fn adds() {
    assert_eq!(calc::add(2, 3), 5);
}

#[test]
fn the_binary_prints_the_sum() {
    let out = std::process::Command::new(env!("CARGO_BIN_EXE_calc")).output().unwrap();
    assert_eq!(String::from_utf8_lossy(&out.stdout).trim(), "5");
}
"""


def _rust_project(root: Path, body: str) -> Path:
    return _files(
        root,
        {
            "Cargo.toml": '[package]\nname = "calc"\nversion = "0.1.0"\nedition = "2021"\n',
            "src/lib.rs": f"pub fn add(a: i32, b: i32) -> i32 {{ {body} }}\n\n"
            '#[cfg(test)]\nmod tests {\n    #[test]\n    fn mine() { panic!("mine"); }\n}\n',
            "src/main.rs": 'fn main() { println!("{}", calc::add(2, 3)); }\n',
            "tests/mine.rs": '#[test]\nfn mine() { panic!("mine"); }\n',
        },
    )


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")
def test_rust_hidden_tests_decide_the_grade(tmp_path):
    task = _task(tmp_path, {"calc.rs": _RUST_HIDDEN})
    assert task.language == "rust"

    right = grade(task, _rust_project(tmp_path / "right", "a + b"))
    wrong = grade(task, _rust_project(tmp_path / "wrong", "a - b"))

    assert (right.status, right.summary) == ("passed", "pass 2, fail 0"), right.output
    assert (wrong.status, wrong.summary) == ("failed", "pass 0, fail 2"), wrong.output
    assert (tmp_path / "right" / "tests" / "certo_hidden_calc.rs").is_file()


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")
def test_node_packages_are_installed_before_the_hidden_tests(tmp_path):
    hidden = (
        "const test = require('node:test');\n"
        "const assert = require('node:assert');\n"
        "const { add } = require('../calc.js');\n"
        "test('adds', () => assert.strictEqual(add(2, 3), 5));\n"
    )
    task = _task(tmp_path, {"calc.test.js": hidden})
    # A local package: npm installs it with no network.
    workspace = _files(
        tmp_path / "ws",
        {
            "package.json": '{"name": "ws", "version": "1.0.0", '
            '"dependencies": {"adder": "file:./adder"}}\n',
            "adder/package.json": '{"name": "adder", "version": "1.0.0", "main": "index.js"}\n',
            "adder/index.js": "module.exports = (a, b) => a + b;\n",
            "calc.js": "const adder = require('adder');\nexports.add = adder;\n",
        },
    )

    result = grade(task, workspace)

    assert result.status == "passed", result.output
    assert (workspace / "node_modules" / "adder").exists()


def test_a_node_package_that_wont_install_is_an_error(tmp_path):
    task = _task(tmp_path, {"t.test.js": "require('node:test');\n"})
    workspace = _files(
        tmp_path / "ws",
        {"package.json": '{"name": "ws", "dependencies": {"missing": "file:./missing"}}\n'},
    )

    class Runner(bench_tasks.LocalRunner):
        def which(self, name):
            return name

        def run(self, command, *, cwd, env=None, timeout):
            from certo.project_env import RunResult

            return RunResult(returncode=1, output="npm ERR! missing\n")

    result = grade(task, workspace, Runner())

    assert result.status == "error"
    assert (
        result.summary == "could not install the project's packages for grading: npm ERR! missing"
    )
    assert result.command == "npm install --ignore-scripts --no-audit --no-fund"


def test_milestone_counts_read_pytests_report_of_every_test():
    from certo.bench_tasks import milestone_counts

    output = (
        "PASSED .certo_hidden_tests/test_a.py::test_m1_numbers[42-42]\n"
        "PASSED .certo_hidden_tests/test_a.py::test_m1_text\n"
        "FAILED .certo_hidden_tests/test_a.py::test_m1_cells - assert 1 == 2\n"
        "FAILED .certo_hidden_tests/test_b.py::test_m3_sum - boom\n"
        "PASSED .certo_hidden_tests/test_b.py::test_other\n"
        "ERROR .certo_hidden_tests/test_c.py - ImportError\n"
    )

    assert milestone_counts(output) == {1: (2, 3), 3: (0, 1)}
    assert milestone_counts("PASSED x.py::test_plain\n") is None


@pytest.mark.parametrize(
    ("name", "milestones", "tests"), [("spreadsheet", 5, 111), ("expenses", 4, 80)]
)
def test_a_task_in_milestones_is_graded_per_milestone(
    tmp_path, project_venv, name, milestones, tests
):
    from certo.bench_tasks import load_task

    task = load_task(Path(__file__).resolve().parent.parent / "app-tasks" / name)
    result = grade(task, _workspace(tmp_path, task, project_venv, solved=True))

    assert result.status == "passed", result.summary
    assert sorted(result.by_milestone) == list(range(1, milestones + 1))
    assert all(passed == total for passed, total in result.by_milestone.values())
    assert sum(total for _, total in result.by_milestone.values()) == tests


def test_a_bundled_task_has_no_count_per_milestone(tmp_path, project_venv):
    task = next(t for t in TASKS if t.name == "slugify")
    result = grade(task, _workspace(tmp_path, task, project_venv, solved=True))
    assert result.by_milestone is None
