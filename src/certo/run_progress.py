"""The progress line: where a run in the terminal is, in one line.

A run prints the agent's actions and Certo's notices as they happen, but
nothing that sums up where it is. While the agent works, Certo prints one
line every `CERTO_PROGRESS_SECONDS` (two minutes by default), and one more
after each check run and when a fix attempt starts:

    Progress: milestone 2 of 4 · fix attempt 1 of 2 · checks failed: pytest (2 failed) · 6m 12s · $0.0310

Only a terminal run asks for it (cli.py); the server, the MCP server and
the benchmark don't. As for the cost limit (cost_limit.py), each
conversation gets its own, and a watcher thread prints it while
`conversation.run()` goes. It reads, never changes, the run.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .cost_limit import conversation_cost
from .run_summary import format_duration


@dataclass
class RunProgress:
    """What the line shows. The caller sets `where` (the milestone) and
    `cost_before` (what earlier milestones cost); the run sets the rest."""

    say: Callable[[str], None]
    every_seconds: float
    started: float = field(default_factory=time.monotonic)
    where: str = ""
    cost_before: float = 0.0
    model: str = ""
    fix: str = ""
    checks: str = ""

    def line(self, spent: float) -> str:
        parts = [p for p in (self.where, self.model, self.fix, self.checks) if p]
        parts.append(format_duration(time.monotonic() - self.started))
        parts.append(f"${self.cost_before + spent:.4f}")
        return "Progress: " + " · ".join(parts)


@dataclass
class _Attached:
    progress: RunProgress
    spent_before: float
    start: float  # the conversation's own cost when it was attached

    def say(self, conversation: Any) -> None:
        spent = self.spent_before + conversation_cost(conversation) - self.start
        self.progress.say(self.progress.line(spent))


_attached: weakref.WeakKeyDictionary[Any, _Attached] = weakref.WeakKeyDictionary()


def attach_progress(
    conversation: Any,
    progress: RunProgress | None,
    spent_before: float = 0.0,
    model: str = "",
) -> None:
    """Show `progress` for `conversation` (None: no line), counting
    `spent_before` (independent tests, earlier rungs) as already spent.
    `model` names an escalation rung's model."""
    if progress is None:
        return
    progress.model = model
    progress.fix = ""
    _attached[conversation] = _Attached(progress, spent_before, conversation_cost(conversation))


def checks_text(run: Any) -> str:
    """A check run in a few words: `checks verified`, or the checks that
    failed or timed out, with their summary."""
    bad = [c for c in run.checks if c.status in ("failed", "timed_out")]
    if not bad:
        return f"checks {run.state}"
    named = ", ".join(f"{c.name} ({c.summary})" if c.summary else c.name for c in bad)
    return f"checks {run.state}: {named}"


def checks_ran(conversation: Any, run: Any) -> None:
    """After a check run: show its result, now and in every later line."""
    found = _attached.get(conversation)
    if found is not None:
        found.progress.checks = checks_text(run)
        found.say(conversation)


def fix_attempt(conversation: Any, number: int, total: int) -> None:
    """A fix attempt starts."""
    found = _attached.get(conversation)
    if found is not None:
        found.progress.fix = f"fix attempt {number} of {total}"
        found.say(conversation)


@contextmanager
def report_progress(conversation: Any) -> Iterator[None]:
    """While the block runs, print the line every `every_seconds`. No-op
    for a conversation with no progress attached."""
    found = _attached.get(conversation)
    if found is None or found.progress.every_seconds <= 0:
        yield
        return
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(found.progress.every_seconds):
            try:
                found.say(conversation)
            except Exception:  # noqa: BLE001 - a line, never the run's outcome
                return

    watcher = threading.Thread(target=watch, name="certo-progress", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        stop.set()
        watcher.join()
