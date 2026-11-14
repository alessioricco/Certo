"""Stop the processes a run left behind.

The agent can start a command in the background (`npm run test:e2e &`, a
dev server). Its terminal (often a tmux server) isn't a child of Certo, and
such a process outlives the run: in a user's milestone run a test runner
and two preview servers ran on for minutes after the run ended. At the end
of a run, after the conversation is closed, Certo stops every process that
started during the run and works inside the project folder (its working
folder, or a path on its command line, is in the project), and says which.

Only at the end, never in the middle: the agent's own terminal would be
one of them. Certo's own process and its ancestors are never touched.
Local execution only (in Docker the container goes away).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass

import psutil

# How long a process gets to stop after SIGTERM before SIGKILL.
_GRACE_SECONDS = 3.0
# A process created this little before the run's start counts as the run's
# (clocks and creation times are not exact).
_START_SLACK_SECONDS = 1.0


@dataclass(frozen=True)
class Leftover:
    pid: int
    name: str


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:  # different drives (Windows)
        return False


def _ours() -> set[int]:
    """Certo's own process and its ancestors: never stopped."""
    pids = {os.getpid()}
    try:
        for parent in psutil.Process(os.getpid()).parents():
            pids.add(parent.pid)
    except psutil.Error:
        pass
    return pids


def _works_in(process: psutil.Process, root: str) -> bool:
    try:
        cwd = process.cwd()
        if cwd and _inside(cwd, root):
            return True
    except psutil.Error:
        pass
    try:
        return any(os.path.isabs(arg) and _inside(arg, root) for arg in process.cmdline()[1:])
    except psutil.Error:
        return False


def _is_terminal_server(process: psutil.Process) -> bool:
    """A tmux server: shared with the user's own tmux sessions, never ours
    to stop (the SDK closes its own session)."""
    try:
        return "tmux" in process.name().lower()
    except psutil.Error:
        return True


def _is_terminal_shell(process: psutil.Process) -> bool:
    """The agent's terminal itself: a direct child of Certo (the SDK's
    subprocess terminal) or of a tmux server (a tmux pane). The SDK owns
    and closes those; what was started from them is what gets stopped."""
    try:
        parent = process.parent()
    except psutil.Error:
        return False
    if parent is None:
        return False
    return parent.pid == os.getpid() or _is_terminal_server(parent)


def find_leftovers(workspace: str, started_at: float) -> list[psutil.Process]:
    """The processes that started after `started_at` (a time.time()) and work
    inside `workspace`, Certo's own excluded."""
    root = os.path.realpath(workspace)
    ours = _ours()
    found = []
    for process in psutil.process_iter(["pid", "create_time"]):
        try:
            if process.pid in ours or _is_terminal_server(process) or _is_terminal_shell(process):
                continue
            created = process.info.get("create_time") or 0.0
            if created < started_at - _START_SLACK_SECONDS:
                continue
            if _works_in(process, root):
                found.append(process)
        except psutil.Error:
            continue
    return found


def stop(processes: Iterable[psutil.Process]) -> list[Leftover]:
    """Stop `processes` (and their children): SIGTERM, then SIGKILL for any
    still running after a few seconds. Returns those that were running."""
    targets: dict[int, psutil.Process] = {}
    for process in processes:
        try:
            targets[process.pid] = process
            for child in process.children(recursive=True):
                targets.setdefault(child.pid, child)
        except psutil.Error:
            continue
    stopped: list[Leftover] = []
    for process in targets.values():
        try:
            name = process.name()
            process.terminate()
            stopped.append(Leftover(process.pid, name))
        except psutil.Error:
            continue
    _gone, alive = psutil.wait_procs(list(targets.values()), timeout=_GRACE_SECONDS)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    return stopped


def stop_leftovers(workspace: str, started_at: float) -> list[Leftover]:
    """Find and stop what the run left behind. Never raises."""
    try:
        return stop(find_leftovers(workspace, started_at))
    except Exception:  # noqa: BLE001 - cleanup must never fail a run
        return []


def describe(stopped: list[Leftover]) -> str:
    names = sorted({s.name for s in stopped})
    shown = ", ".join(names[:5]) + (", ..." if len(names) > 5 else "")
    return (
        f"Certo: stopped {len(stopped)} process(es) the agent left running in the "
        f"project ({shown})."
    )


def now() -> float:
    return time.time()
