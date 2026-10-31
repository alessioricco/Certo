"""The expense ledger, milestone 4: the command line, run as people run
it. Test names start with m4_."""

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path.cwd() / "ledger.py"


def run(*args, timeout=20):
    return subprocess.run(
        [sys.executable, str(PROGRAM), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def lines(result):
    return result.stdout.splitlines()


def test_m4_add_prints_the_id_and_saves(tmp_path):
    path = tmp_path / "l.json"
    first = run(path, "add", "2026-03-01", "12.50", "Food", "lunch", "with", "Ana")
    assert first.returncode == 0, first.stderr
    assert lines(first) == ["1"]
    second = run(path, "add", "2026-03-02", "3", "bus")
    assert lines(second) == ["2"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["next_id"] == 3
    assert data["entries"][0] == {
        "id": 1,
        "date": "2026-03-01",
        "cents": 1250,
        "category": "food",
        "note": "lunch with Ana",
    }
    assert data["entries"][1]["note"] == ""


def test_m4_list_prints_tab_separated_fields(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-05", "2.5", "bus")
    run(path, "add", "2026-03-01", "12", "food", "lunch")
    result = run(path, "list")
    assert result.returncode == 0, result.stderr
    assert lines(result) == [
        "2\t2026-03-01\t12.00\tfood\tlunch",
        "1\t2026-03-05\t2.50\tbus\t",
    ]


def test_m4_list_of_an_empty_or_missing_file_prints_nothing(tmp_path):
    result = run(tmp_path / "l.json", "list")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_m4_remove_takes_an_entry_away(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    run(path, "add", "2026-03-02", "2", "bus")
    result = run(path, "remove", "1")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert [line.split("\t")[0] for line in lines(run(path, "list"))] == ["2"]
    assert lines(run(path, "add", "2026-03-03", "1", "food")) == ["3"]


def test_m4_report_prints_totals_by_category(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "12.50", "food")
    run(path, "add", "2026-03-02", "2.25", "bus")
    run(path, "add", "2026-03-03", "7.5", "food")
    run(path, "add", "2026-04-01", "800", "rent")
    result = run(path, "report")
    assert result.returncode == 0, result.stderr
    assert lines(result) == ["bus\t2.25", "food\t20.00", "rent\t800.00", "total\t822.25"]


def test_m4_report_of_a_month(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "12.50", "food")
    run(path, "add", "2026-04-01", "800", "rent")
    result = run(path, "report", "2026-04")
    assert result.returncode == 0, result.stderr
    assert lines(result) == ["rent\t800.00", "total\t800.00"]


def test_m4_report_with_no_entries(tmp_path):
    result = run(tmp_path / "l.json", "report")
    assert result.returncode == 0, result.stderr
    assert lines(result) == ["total\t0.00"]


def test_m4_reading_commands_leave_the_file_as_it_was(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    before = path.read_bytes()
    run(path, "list")
    run(path, "report")
    assert path.read_bytes() == before


def test_m4_reading_a_missing_file_creates_none(tmp_path):
    path = tmp_path / "l.json"
    run(path, "list")
    run(path, "report")
    assert not path.exists()


def errors_and_keeps_the_file(path, *args):
    before = path.read_bytes() if path.exists() else None
    result = run(path, *args)
    assert result.returncode == 1
    assert result.stderr.startswith("Error:")
    assert (path.read_bytes() if path.exists() else None) == before


def test_m4_no_command_is_an_error(tmp_path):
    errors_and_keeps_the_file(tmp_path / "l.json")


def test_m4_no_arguments_prints_the_usage():
    result = run()
    assert result.returncode == 2
    assert result.stderr.startswith("usage:")


def test_m4_an_unknown_command_is_an_error(tmp_path):
    errors_and_keeps_the_file(tmp_path / "l.json", "delete", "1")


def test_m4_add_with_missing_arguments_is_an_error(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    errors_and_keeps_the_file(path, "add", "2026-03-01", "1")


def test_m4_add_with_an_invalid_value_is_an_error(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    errors_and_keeps_the_file(path, "add", "2026-02-30", "1", "food")
    errors_and_keeps_the_file(path, "add", "2026-03-01", "0", "food")
    assert lines(run(path, "add", "2026-03-02", "1", "food")) == ["2"]


def test_m4_removing_an_unknown_id_is_an_error(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    errors_and_keeps_the_file(path, "remove", "7")
    errors_and_keeps_the_file(path, "remove", "one")


def test_m4_a_report_of_an_invalid_month_is_an_error(tmp_path):
    path = tmp_path / "l.json"
    run(path, "add", "2026-03-01", "1", "food")
    errors_and_keeps_the_file(path, "report", "2026-3")
