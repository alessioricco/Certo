"""leftovers.py: processes a run left running are stopped at its end.
Real short-lived processes, no model; POSIX only (uses `sh` and `sleep`)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from certo import leftovers

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses sh and sleep")


def _background_sleep(folder) -> int:
    """`sleep` started in the background from a shell that then exits, as an
    agent's `cmd &` does: the sleep outlives its shell. Returns its pid."""
    out = subprocess.run(
        ["sh", "-c", "sleep 60 >/dev/null 2>&1 & echo $!"],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


def _running(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_a_background_process_in_the_project_is_stopped(tmp_path):
    started = time.time()
    pid = _background_sleep(tmp_path)
    assert _running(pid)

    stopped = leftovers.stop_leftovers(str(tmp_path), started)

    assert [s.pid for s in stopped] == [pid]
    assert stopped[0].name == "sleep"
    for _ in range(50):
        if not _running(pid):
            break
        time.sleep(0.05)
    assert not _running(pid)


def test_a_process_outside_the_project_or_older_than_the_run_is_left_alone(tmp_path):
    other = tmp_path / "other"
    project = tmp_path / "project"
    other.mkdir()
    project.mkdir()
    old = _background_sleep(project)
    time.sleep(1.5)  # more than the start slack
    started = time.time()
    outside = _background_sleep(other)
    try:
        assert leftovers.find_leftovers(str(project), started) == []
    finally:
        for pid in (old, outside):
            psutil.Process(pid).kill()


def test_certos_own_process_is_never_a_leftover(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # restored after the test

    found = leftovers.find_leftovers(str(tmp_path), 0.0)

    assert os.getpid() not in [p.pid for p in found]


def test_the_notice_names_the_programs():
    stopped = [
        leftovers.Leftover(1, "node"),
        leftovers.Leftover(2, "node"),
        leftovers.Leftover(3, "esbuild"),
    ]

    assert leftovers.describe(stopped) == (
        "Certo: stopped 3 process(es) the agent left running in the project (esbuild, node)."
    )
