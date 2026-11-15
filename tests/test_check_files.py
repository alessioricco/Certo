import os
from types import SimpleNamespace

import pytest

from certo.check_files import (
    CheckFileChange,
    changes_note,
    check_file_changes,
    is_check_file,
    required_texts,
    snapshot_check_files,
)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "tests/fixtures/data.json",
        "pkg/test_util.py",
        "pkg/util_test.py",
        "conftest.py",
        "main_test.go",
        "src/app.test.ts",
        "src/App.spec.jsx",
        "__tests__/app.js",
        "src/test/java/AppTest.java",
        "pyproject.toml",
        "pytest.ini",
        "package.json",
        "tsconfig.app.json",
        "eslint.config.mjs",
        ".eslintrc.json",
        "Cargo.toml",
    ],
)
def test_check_files(path):
    assert is_check_file(path)


@pytest.mark.parametrize(
    "path", ["app.py", "src/latest.py", "README.md", "src/contest.ts", "testing_notes.md"]
)
def test_other_files(path):
    assert not is_check_file(path)


def _write(root, path, text):
    full = root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, so the file has "\n" line endings on Windows too.
    full.write_bytes(text.encode())


def test_changed_and_deleted_check_files_are_found(tmp_path):
    _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert f() == 1\n    assert g()\n")
    _write(tmp_path, "tests/test_b.py", "def test_b():\n    assert True\n")
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "app.py", "x = 1\n")
    before = snapshot_check_files(str(tmp_path))
    assert "app.py" not in before

    _write(tmp_path, "tests/test_a.py", "def test_a():\n    pass\n")
    os.remove(tmp_path / "tests" / "test_b.py")
    _write(tmp_path, "tests/test_new.py", "def test_new():\n    pass\n")
    _write(tmp_path, "app.py", "x = 2\n")

    changes = check_file_changes(str(tmp_path), before)

    assert changes == (
        CheckFileChange(
            os.path.join("tests", "test_a.py"),
            False,
            1,
            0,
            1,
            ("-     assert f() == 1", "-     assert g()", "+     pass"),
        ),
        CheckFileChange(os.path.join("tests", "test_b.py"), True, 2, 0),
    )


def test_nothing_changed(tmp_path):
    _write(tmp_path, "tests/test_a.py", "def test_a():\n    pass\n")
    before = snapshot_check_files(str(tmp_path))
    assert check_file_changes(str(tmp_path), before) == ()


def test_the_note_lists_at_most_five():
    changes = tuple(CheckFileChange(f"tests/test_{i}.py", False, 1, 0) for i in range(7))
    note = changes_note(changes)
    assert note.startswith("The agent changed 7 files the checks rely on: tests/test_0.py")
    assert "tests/test_4.py (1 line removed), and 2 more." in note
    assert "tests/test_5.py" not in note


def test_the_note_for_a_deleted_file():
    note = changes_note((CheckFileChange("pytest.ini", True, 3, 0),))
    assert "The agent changed 1 file the checks rely on: pytest.ini (deleted)." in note


def test_a_rewritten_line_is_changed_not_removed(tmp_path):
    _write(tmp_path, "test_inv.py", "from inv import A\n\ndef test_a():\n    assert A()\n")
    before = snapshot_check_files(str(tmp_path))
    _write(
        tmp_path,
        "test_inv.py",
        "from inv import A, B\n\ndef test_a():\n    assert A()\n\ndef test_b():\n    assert B()\n",
    )
    (change,) = check_file_changes(str(tmp_path), before)
    assert change.described == "test_inv.py (1 line changed, 3 lines added)"


def test_line_endings_only(tmp_path):
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    before = snapshot_check_files(str(tmp_path))
    (tmp_path / "pytest.ini").write_bytes(b"[pytest]\r\n")
    (change,) = check_file_changes(str(tmp_path), before)
    assert change.described == "pytest.ini (line endings only)"


def test_an_edit_an_acceptance_check_requires_is_left_out(tmp_path):
    # A user's run, 2026-11-14: a version bump an acceptance check asked
    # for was flagged as a change to the checks.
    _write(tmp_path, "package.json", '{\n  "name": "game",\n  "version": "0.6.0"\n}\n')
    before = snapshot_check_files(str(tmp_path))
    _write(tmp_path, "package.json", '{\n  "name": "game",\n  "version": "0.7.0"\n}\n')
    check = SimpleNamespace(
        kind="file_contains", path="package.json", contains='"version": "0.7.0"'
    )
    required = required_texts([check])
    assert check_file_changes(str(tmp_path), before, required) == ()
    # Anything more than what the check asks for is still reported.
    _write(tmp_path, "package.json", '{\n  "version": "0.7.0"\n}\n')
    (change,) = check_file_changes(str(tmp_path), before, required)
    assert change.lines == (
        '-   "name": "game",',
        '-   "version": "0.6.0"',
        '+   "version": "0.7.0"',
    )


def test_long_diffs_are_cut(tmp_path):
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    before = snapshot_check_files(str(tmp_path))
    _write(tmp_path, "pytest.ini", "[pytest]\n" + "".join(f"x{i} = 1\n" for i in range(20)))
    (change,) = check_file_changes(str(tmp_path), before)
    assert len(change.lines) == 13
    assert change.lines[-1] == "... and 8 more lines"
