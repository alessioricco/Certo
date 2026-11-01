"""Cancel a run from another thread (the MCP server's `run_cancel`).

`stream_task(cancel=event)` makes `event` the run's cancel token. Setting it
pauses the conversation (`conversation.pause()`, which takes effect between
agent steps, as the deadline does: deadline.py), and the runner then raises
`RunCancelled`. A check or a model call already under way finishes first.
The run is saved as interrupted, like Ctrl-C, so `certo --resume` continues
it from its checkpoint.

The token is a context variable, set for the thread that runs the task: every
conversation of the run (escalation rungs, retries) sees it without being
passed it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


class RunCancelled(Exception):
    """The run was cancelled before it ended."""

    def __init__(self) -> None:
        super().__init__("cancelled")


_token: ContextVar[threading.Event | None] = ContextVar("certo_cancel", default=None)


@contextmanager
def cancel_token(event: threading.Event | None) -> Iterator[None]:
    """Make `event` the cancel token of the run in this block."""
    reset = _token.set(event)
    try:
        yield
    finally:
        _token.reset(reset)


def raise_if_cancelled() -> None:
    event = _token.get()
    if event is not None and event.is_set():
        raise RunCancelled()


@contextmanager
def stop_when_cancelled(conversation: Any) -> Iterator[None]:
    """While the block runs, pause `conversation` as soon as the token is set."""
    event = _token.get()
    if event is None:
        yield
        return
    done = threading.Event()

    def watch() -> None:
        while not done.is_set():
            if event.wait(0.5):
                conversation.pause()
                return

    watcher = threading.Thread(target=watch, name="certo-cancel", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        done.set()
        watcher.join()
