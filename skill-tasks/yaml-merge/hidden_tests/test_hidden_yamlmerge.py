"""yamlmerge, as a module and as the program people run."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import yamlmerge

PROGRAM = Path.cwd() / "yamlmerge.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(PROGRAM), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_merge_is_deep_and_later_wins():
    a = {"db": {"host": "a", "port": 1}, "debug": False}
    b = {"db": {"port": 2, "user": "x"}, "debug": True}
    assert yamlmerge.merge(a, b) == {"db": {"host": "a", "port": 2, "user": "x"}, "debug": True}


def test_merge_three_levels_deep():
    a = {"a": {"b": {"c": 1, "d": 2}}}
    b = {"a": {"b": {"d": 3}}}
    assert yamlmerge.merge(a, b) == {"a": {"b": {"c": 1, "d": 3}}}


def test_lists_and_null_replace():
    a = {"hosts": [1, 2], "x": {"y": 1}, "z": 5}
    b = {"hosts": [3], "x": None, "z": [1]}
    assert yamlmerge.merge(a, b) == {"hosts": [3], "x": None, "z": [1]}


def test_a_mapping_replaces_a_scalar_and_back():
    assert yamlmerge.merge({"a": 1}, {"a": {"b": 2}}) == {"a": {"b": 2}}
    assert yamlmerge.merge({"a": {"b": 2}}, {"a": 1}) == {"a": 1}


def test_merge_changes_nothing_it_was_given():
    a = {"db": {"host": "a"}}
    b = {"db": {"port": 2}}
    yamlmerge.merge(a, b)
    assert a == {"db": {"host": "a"}}
    assert b == {"db": {"port": 2}}


def test_merge_of_nothing_and_of_one():
    assert yamlmerge.merge() == {}
    assert yamlmerge.merge({"a": 1}) == {"a": 1}


def test_load_and_merge_reads_files_in_order(tmp_path):
    a = write(tmp_path, "a.yaml", "name: base\nlevels:\n  info: true\n")
    b = write(tmp_path, "b.yaml", "levels:\n  debug: true\n")
    assert yamlmerge.load_and_merge([a, b]) == {
        "name": "base",
        "levels": {"info": True, "debug": True},
    }


def test_an_empty_file_counts_as_empty(tmp_path):
    a = write(tmp_path, "a.yaml", "x: 1\n")
    empty = write(tmp_path, "empty.yaml", "")
    assert yamlmerge.load_and_merge([a, empty]) == {"x": 1}


def test_a_top_level_list_is_refused(tmp_path):
    bad = write(tmp_path, "list.yaml", "- 1\n- 2\n")
    with pytest.raises(ValueError, match="list.yaml"):
        yamlmerge.load_and_merge([bad])


def test_the_program_prints_sorted_yaml(tmp_path):
    a = write(tmp_path, "a.yaml", "zeta: 1\nalpha:\n  b: 2\n")
    b = write(tmp_path, "b.yaml", "alpha:\n  a: 1\n")
    result = run(a, b)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "alpha:\n  a: 1\n  b: 2\nzeta: 1\n"
    assert yaml.safe_load(result.stdout) == {"alpha": {"a": 1, "b": 2}, "zeta": 1}


def test_no_file_is_a_usage_error():
    result = run()
    assert result.returncode == 2
    assert result.stderr.strip()


@pytest.mark.parametrize(
    ("name", "text"),
    [("list.yaml", "- 1\n"), ("broken.yaml", "a: [1, 2\n")],
)
def test_bad_files_exit_1_naming_the_file(tmp_path, name, text):
    path = write(tmp_path, name, text)
    result = run(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert name in result.stderr


def test_a_missing_file_exits_1(tmp_path):
    result = run(tmp_path / "missing.yaml")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "missing.yaml" in result.stderr
