"""Tell the agent what Certo will check, and warn it before time runs out.

Two messages, both generic (they name only the task's own checks):

- With the task: the acceptance checks Certo runs at the end, in plain
  words, so the agent knows the task isn't done until they hold. Before,
  the checks were taken out of the task text and never shown, and closing
  steps (a changelog entry, a report file) were the ones a deadline cut.
- Before the deadline: one wrap-up message, a margin before the time
  budget ends (15% of it, between 2 and 10 minutes), naming the checks
  that don't hold yet. The conversation is paused between agent steps
  (as at the deadline, deadline.py), the message is sent, and the run
  goes on.

Acceptance checks are the user's own requirements, so showing them is
not like showing independent tests (which stay hidden, DECISIONS.md).
"""

from __future__ import annotations

import math
import threading
import time
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .acceptance import AcceptanceCheck, evaluate_acceptance_checks

MARGIN_FRACTION = 0.15
MIN_MARGIN_SECONDS = 120.0
MAX_MARGIN_SECONDS = 600.0
_POLL_SECONDS = 2.0


def describe_check(check: AcceptanceCheck) -> str:
    """One acceptance check in plain words."""
    if check.kind == "file_exists":
        text = f"the file {check.path} exists"
    else:
        text = f'{check.path} contains the text "{check.contains}"'
    if check.description:
        text += f" ({check.description})"
    if not check.required:
        text += " (optional)"
    return text


def acceptance_brief(checks: Sequence[AcceptanceCheck] | None) -> str:
    """The lines added to the task message, or "" without checks."""
    if not checks:
        return ""
    lines = "\n".join(f"- {describe_check(c)}" for c in checks)
    return (
        "\n\nWhen you finish, Certo checks that each of these holds; the task "
        f"isn't done until the required ones do:\n{lines}"
    )


def margin_seconds(budget_seconds: float) -> float:
    """How long before the deadline the wrap-up message goes."""
    return min(MAX_MARGIN_SECONDS, max(MIN_MARGIN_SECONDS, MARGIN_FRACTION * budget_seconds))


@dataclass
class WrapUp:
    """One run's wrap-up: when it is due, and whether it was sent."""

    at: float  # time.monotonic() when the message is due
    deadline: float
    workspace: str
    checks: Sequence[AcceptanceCheck] = ()
    due: bool = False
    sent: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def message(self, now: float | None = None) -> str:
        now = time.monotonic() if now is None else now
        minutes = max(1, math.ceil((self.deadline - now) / 60))
        text = (
            f"Certo: about {minutes} minute(s) of the time budget are left. Don't start "
            "new work now: finish what is open, make sure the project's checks pass, "
            "and record what you did where the task asks for it."
        )
        failing = [
            r.check
            for r in evaluate_acceptance_checks(self.workspace, list(self.checks))
            if not r.passed and r.check.required
        ]
        if failing:
            lines = "\n".join(f"- {describe_check(c)}" for c in failing)
            text += f"\nThese checks Certo runs at the end don't hold yet:\n{lines}"
        return text


_wrap_ups: weakref.WeakKeyDictionary[Any, WrapUp] = weakref.WeakKeyDictionary()


def register(
    conversation: Any,
    *,
    deadline: float,
    budget_seconds: float,
    workspace: str,
    checks: Sequence[AcceptanceCheck] | None,
) -> WrapUp | None:
    """Plan the wrap-up message for `conversation`. None for a run with no
    time budget, or with too little time left for one."""
    if not math.isfinite(deadline) or budget_seconds <= 0:
        return None
    margin = margin_seconds(budget_seconds)
    if margin >= budget_seconds:  # a budget too short for a wrap-up
        return None
    at = deadline - margin
    if at <= time.monotonic():
        return None
    wrap = WrapUp(at=at, deadline=deadline, workspace=workspace, checks=tuple(checks or ()))
    try:
        _wrap_ups[conversation] = wrap
    except TypeError:  # an object that can't be weakly referenced (tests)
        return None
    return wrap


def wrap_up_for(conversation: Any) -> WrapUp | None:
    try:
        return _wrap_ups.get(conversation)
    except TypeError:
        return None


@contextmanager
def pause_for_wrap_up(conversation: Any) -> Iterator[None]:
    """While a run goes, pause it (between agent steps) when its wrap-up
    message is due, so the runner can send it and go on."""
    wrap = wrap_up_for(conversation)
    if wrap is None or wrap.sent:
        yield
        return
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(_POLL_SECONDS):
            if time.monotonic() >= wrap.at:
                with wrap._lock:
                    if wrap.sent or wrap.due:
                        return
                    wrap.due = True
                conversation.pause()
                return

    watcher = threading.Thread(target=watch, name="certo-wrap-up", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        stop.set()
        watcher.join(timeout=_POLL_SECONDS + 1)


def take_due_message(conversation: Any, now: float | None = None) -> str | None:
    """The wrap-up message, once, when it is due and time is left."""
    wrap = wrap_up_for(conversation)
    if wrap is None:
        return None
    now = time.monotonic() if now is None else now
    with wrap._lock:
        if not wrap.due or wrap.sent or now >= wrap.deadline:
            return None
        wrap.sent = True
    return wrap.message(now)
