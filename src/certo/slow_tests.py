"""Tell the agent once when its own test run is slow for the time budget.

Seen in a user's milestone project (2026-11-14): a browser test suite took
9 minutes, failing tests each waited out a 30-second timeout, and the agent
ran the whole suite more than once per milestone inside a 30-minute budget.
The task can't be expected to say "run fewer tests"; Certo sees each
command the agent runs and how long it took, so it says it.

A callback on the conversation times every terminal command that looks
like a test run (`looks_like_test_command`). When one took at least
`SLOW_FRACTION` of the time budget (and at least `MIN_SLOW_SECONDS`), the
conversation is paused between agent steps (as for the wrap-up message,
wrap_up.py), one note is sent, and the run goes on. Once per conversation:
a reminder repeated every step would cost more than it saves.

Generic on purpose: the note names no tool or framework, only the command
the agent itself ran.
"""

from __future__ import annotations

import math
import re
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

SLOW_FRACTION = 0.10
MIN_SLOW_SECONDS = 60.0
_POLL_SECONDS = 2.0
_COMMAND_SHOWN = 120

# Words that mark a command as a test run in the common ecosystems. A test
# command that matches none of them just gets no note.
_TEST_WORDS = re.compile(
    r"(?<![\w-])("
    r"tests?|spec|e2e|pytest|unittest|tox|nox|jest|vitest|mocha|jasmine|karma|"
    r"playwright|cypress|rspec|phpunit|ctest|junit|xunit|nunit"
    r")(?![\w-])",
    re.IGNORECASE,
)


def looks_like_test_command(command: str) -> bool:
    return bool(_TEST_WORDS.search(command))


def slow_threshold(budget_seconds: float) -> float:
    """How long one test run may take before the note."""
    return max(MIN_SLOW_SECONDS, SLOW_FRACTION * budget_seconds)


def _short(command: str) -> str:
    one_line = " ".join(command.split())
    if len(one_line) <= _COMMAND_SHOWN:
        return one_line
    return one_line[: _COMMAND_SHOWN - 1] + "…"


def note_text(command: str, seconds: float, budget_seconds: float, left_seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    share = round(100 * seconds / budget_seconds)
    left = (
        f", and about {max(1, math.floor(left_seconds / 60))} minute(s) are left"
        if math.isfinite(left_seconds)
        else ""
    )
    return (
        f"Certo: this test run took about {minutes} minute(s), {share}% of the time "
        f"budget{left}: `{_short(command)}`. "
        "While you work, run only the tests for what you changed (one file, one "
        "test name, one configuration); run the whole suite once, when you are done. "
        "A test that fails on a timeout costs the whole timeout on every run: run it "
        "alone and fix it, or narrow it, before running the suite again."
    )


@dataclass
class SlowTestWatch:
    """One conversation's test-run timer. Its `__call__` is a conversation
    callback (it runs inside the SDK's event loop, holding the state lock,
    so it only records; `pause_for_slow_tests` does the pausing)."""

    budget_seconds: float
    deadline: float = math.inf
    slow: tuple[str, float] | None = None  # (command, seconds)
    due: bool = False
    sent: bool = False
    _started: dict[str, tuple[float, str]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __call__(self, event: Any) -> None:
        kind = type(event).__name__
        if kind == "ActionEvent":
            action = getattr(event, "action", None)
            command = getattr(action, "command", None)
            if (
                getattr(event, "source", None) == "agent"
                and isinstance(command, str)
                and not getattr(action, "is_input", False)
                and looks_like_test_command(command)
            ):
                self._started[event.id] = (time.monotonic(), command)
        elif kind == "ObservationEvent":
            begun = self._started.pop(getattr(event, "action_id", None), None)
            if begun is None:
                return
            started, command = begun
            self.record(command, time.monotonic() - started)

    def record(self, command: str, seconds: float) -> None:
        if seconds < slow_threshold(self.budget_seconds):
            return
        with self._lock:
            if self.sent or self.due:
                return
            self.slow = (command, seconds)
            self.due = True


def new_watch(budget_seconds: float) -> SlowTestWatch | None:
    """A watch for a run with a time budget; None without one."""
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        return None
    return SlowTestWatch(budget_seconds=budget_seconds)


_watches: weakref.WeakKeyDictionary[Any, SlowTestWatch] = weakref.WeakKeyDictionary()


def attach(conversation: Any, watch: SlowTestWatch | None) -> None:
    """Tie `watch` (already among the conversation's callbacks) to it."""
    if watch is None:
        return
    try:
        _watches[conversation] = watch
    except TypeError:  # an object that can't be weakly referenced (tests)
        pass


def watch_for(conversation: Any) -> SlowTestWatch | None:
    try:
        return _watches.get(conversation)
    except TypeError:
        return None


@contextmanager
def pause_for_slow_tests(conversation: Any) -> Iterator[None]:
    """While a run goes, pause it (between agent steps) once a slow test
    run was seen, so the runner can send the note and go on."""
    watch = watch_for(conversation)
    if watch is None or watch.sent:
        yield
        return
    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(_POLL_SECONDS):
            if watch.due:
                conversation.pause()
                return

    poller = threading.Thread(target=poll, name="certo-slow-tests", daemon=True)
    poller.start()
    try:
        yield
    finally:
        stop.set()
        poller.join(timeout=_POLL_SECONDS + 1)


def take_note(conversation: Any, deadline: float, now: float | None = None) -> str | None:
    """The note, once, when a slow test run was seen and time is left."""
    watch = watch_for(conversation)
    if watch is None:
        return None
    now = time.monotonic() if now is None else now
    with watch._lock:
        if not watch.due or watch.sent or watch.slow is None:
            return None
        watch.sent = True
        watch.due = False
    if now >= deadline:
        return None
    command, seconds = watch.slow
    return note_text(command, seconds, watch.budget_seconds, deadline - now)
