"""The interactive session's full screen (DECISIONS.md, 2026-11-16, later;
supersedes "inline, not full-screen").

One prompt_toolkit Application, as other agent terminals have: the
transcript in a scrollable pane at the top (the header first, then what
every run and command prints, colors kept), a bordered input box, and the
status line at the bottom. The mouse wheel and PgUp/PgDn scroll the pane.

While the screen is up, everything printed goes to the pane: `sys.stdout`,
`sys.stderr` and the logging handlers that wrote to them point at it. Every
question asked with `input()` (a run's, `/rollback`'s) is asked in the input
box instead (`LiveRun.ask`), since a second reader of the terminal would
break the screen. Commands run in a thread, as runs do, so the screen keeps
moving. When the session ends, the whole transcript is printed to the
terminal, so it stays in the scrollback as before.

The logic (what a line does, the status text) stays in session.py.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import logging
import re
import shlex
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from .session import (
    Actions,
    LiveRun,
    SessionState,
    _end,
    _run,
    _stop,
    completions,
    handle,
    header,
    status_lines,
)

MAX_LINES = 5000  # the pane keeps the last lines; the printed-back transcript keeps all

# Terminal control codes other than colors: a shell's bracketed-paste and
# cursor switches (`ESC[?2004l`), titles (`ESC]0;...BEL`), and the like.
# The agent's terminal output carries them; on a terminal they were
# invisible, in the pane they'd print as text. Colors (`ESC[...m`) stay.
_CONTROL = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-ln-~]"  # CSI not ending in m
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[@-Z\\-_]"  # other two-character escapes
    r"|[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]"  # control characters but tab, newline, CR, ESC
)


def without_controls(text: str) -> str:
    return _CONTROL.sub("", text)


def _fragments(line: str) -> list[tuple[str, str]]:
    """One line of text with ANSI colors, as prompt_toolkit's styled
    fragments. A carriage return keeps what comes after it, as a terminal
    shows a progress line."""
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text

    line = without_controls(line.rstrip("\r").rsplit("\r", 1)[-1])
    merged: list[tuple[str, str]] = []
    for style, text, *_ in to_formatted_text(ANSI(line)):
        if merged and merged[-1][0] == style:
            merged[-1] = (style, merged[-1][1] + text)
        else:
            merged.append((style, text))
    return merged


class OutputPane(io.TextIOBase):
    """The transcript: written to like a terminal (it stands in for
    `sys.stdout`), kept as styled lines for the screen and as the raw text
    to print back when the session ends. Thread-safe: runs write from
    their own threads."""

    def __init__(self, refresh: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._raw: list[str] = []
        self._lines: list[list[tuple[str, str]]] = []
        self._partial = ""
        self.scroll = 0  # lines up from the bottom; 0 follows the output
        self.refresh = refresh

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def isatty(self) -> bool:
        return True  # colors, as on the terminal

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        raise io.UnsupportedOperation("the session's output pane has no file descriptor")

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            self._raw.append(text)
            parts = (self._partial + text).split("\n")
            self._partial = parts.pop()
            self._lines.extend(_fragments(part) for part in parts)
            if len(self._lines) > MAX_LINES:
                del self._lines[: len(self._lines) - MAX_LINES]
        self.refresh()
        return len(text)

    def line_count(self) -> int:
        with self._lock:
            return len(self._lines) + (1 if self._partial else 0)

    def fragments(self) -> list[tuple[str, str]]:
        """Every line, as the screen shows them."""
        with self._lock:
            lines = list(self._lines)
            partial = self._partial
        if partial:
            lines.append(_fragments(partial))
        out: list[tuple[str, str]] = []
        for i, line in enumerate(lines):
            if i:
                out.append(("", "\n"))
            out.extend(line)
        return out

    def scroll_by(self, lines: int) -> None:
        self.scroll = max(0, min(self.line_count() - 1, self.scroll + lines))

    def clear(self) -> None:
        """Clear the screen; the printed-back transcript keeps everything."""
        with self._lock:
            self._lines, self._partial, self.scroll = [], "", 0
        self.refresh()

    def transcript(self) -> str:
        with self._lock:
            return "".join(self._raw)


@contextlib.contextmanager
def printing_to(pane: OutputPane, ask: Callable[[str], str]) -> Iterator[None]:
    """While the screen is up: stdout, stderr and the logging handlers that
    wrote to them go to the pane, and `input()` asks in the input box."""
    terminal = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    moved: list[tuple[logging.StreamHandler, Any]] = []
    loggers = [logging.getLogger()] + [
        lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if (
                type(handler) is logging.StreamHandler  # not a FileHandler
                and handler.stream in terminal
            ):
                moved.append((handler, handler.stream))
                handler.setStream(pane)
    old = sys.stdout, sys.stderr, builtins.input
    sys.stdout = sys.stderr = pane
    builtins.input = ask
    try:
        yield
    finally:
        sys.stdout, sys.stderr, builtins.input = old
        for handler, stream in moved:
            handler.setStream(stream)


def run_screen(
    state: SessionState,
    actions: Actions,
    *,
    show_header: bool = True,
    first: Sequence[str] = (),
    input: Any = None,
    output: Any = None,
) -> int:
    """The full-screen session. `first`: certo arguments to run as the
    first task. `input`/`output`: prompt_toolkit's, for tests."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.layout.menus import CompletionsMenu
    from prompt_toolkit.layout.processors import BeforeInput
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output.defaults import create_output
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Frame

    pane = OutputPane()
    output = output or create_output(stdout=sys.stdout)  # the terminal, before stdout moves

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            word = document.text_before_cursor
            for name, meta in completions(word):
                yield Completion(name, start_position=-len(word), display_meta=meta)

    class PaneControl(FormattedTextControl):
        """The transcript; its last line stays in view unless scrolled."""

        def __init__(self) -> None:
            super().__init__(
                pane.fragments,
                focusable=False,
                show_cursor=False,
                get_cursor_position=lambda: Point(0, max(0, pane.line_count() - 1 - pane.scroll)),
            )

        def mouse_handler(self, mouse_event):
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                pane.scroll_by(3)
                return None
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                pane.scroll_by(-3)
                return None
            return NotImplemented

    def accept(buffer: Buffer) -> bool:
        text = buffer.text
        pane.scroll = 0
        live = state.live
        if live is not None and live.question:
            print(f"{live.question}{text}")
            live.answer(text)
            return False
        if text.strip():
            print(f"> {text}")
        try:
            if not handle(state, text, actions):
                app.exit(result=0)
        except Exception as exc:  # noqa: BLE001 - said, and the session goes on
            print(f"Error: {exc}")
        return False  # clears the box

    buffer = Buffer(
        multiline=False,
        completer=SlashCompleter(),
        complete_while_typing=True,
        history=InMemoryHistory(),
        accept_handler=accept,
    )

    def prompt() -> str:
        live = state.live
        return live.question if live is not None and live.question else "> "

    def status() -> list[tuple[str, str]]:
        facts, switches = status_lines(state)
        return [("class:status", f" {facts}\n"), ("class:status.keys", f" {switches}")]

    input_window = Window(
        BufferControl(buffer, input_processors=[BeforeInput(prompt, style="class:prompt")]),
        height=Dimension(min=1, max=6),
        wrap_lines=True,
        dont_extend_height=True,  # one line, growing with what is typed
    )
    body = HSplit(
        [
            Window(PaneControl(), wrap_lines=True),
            Frame(input_window),
            Window(FormattedTextControl(status), height=2),
        ]
    )
    root = FloatContainer(
        body,
        floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=12))],
    )

    keys = KeyBindings()

    @keys.add("s-tab")
    def _ask(event) -> None:
        state.cycle("ask")

    @keys.add("c-t")
    def _mode(event) -> None:
        state.cycle("mode")

    @keys.add("c-o")
    def _effort(event) -> None:
        state.cycle("effort")

    @keys.add("c-c")
    def _interrupt(event) -> None:
        if state.live is not None:
            _stop(state, actions)
        elif buffer.text:
            buffer.reset()
        else:
            print("Ctrl-D or /quit ends the session.")

    @keys.add("c-d")
    def _quit(event) -> None:
        if buffer.text:
            buffer.delete()
        else:
            event.app.exit(result=0)

    def page(event) -> int:
        return max(1, event.app.output.get_size().rows - 6)

    @keys.add("pageup")
    def _up(event) -> None:
        pane.scroll_by(page(event))

    @keys.add("pagedown")
    def _down(event) -> None:
        pane.scroll_by(-page(event))

    app: Application = Application(
        layout=Layout(root, focused_element=input_window),
        key_bindings=keys,
        style=Style.from_dict(
            {
                "status": "bg:#262626 #d0d0d0",
                "status.keys": "bg:#262626 #8a8a8a",
                "frame.border": "#5f87af",
                "prompt": "bold",
            }
        ),
        full_screen=True,
        mouse_support=True,
        refresh_interval=0.25,  # the status line moves while a run works
        input=input,
        output=output,
    )
    pane.refresh = app.invalidate
    actions.refresh = app.invalidate

    # Commands run in a thread too, so the screen keeps moving; one that
    # asks (`/rollback`) asks in the input box.
    plain_command, plain_clear = actions.command, actions.clear

    def command(name: str, argv: list[str]) -> int:
        from .cancel import RunCancelled

        busy = state.live is None  # `/ask` during a run leaves the run's line alone
        live = LiveRun(label=f"/{name}", refresh=lambda: actions.refresh()) if busy else None
        if live is not None:
            state.live = live

        def work() -> None:
            try:
                plain_command(name, argv)
            except RunCancelled:
                print("Stopped.")
            except Exception as exc:  # noqa: BLE001 - said, and the session goes on
                print(f"Error: {exc}")
            finally:
                if live is not None and state.live is live:
                    state.live = None
                actions.refresh()

        thread = actions.start(work)
        if live is not None:
            live.thread = thread
        return 0

    def ask(prompt_text: object = "") -> str:
        live = state.live
        if live is None:
            raise EOFError("nothing in the session is waiting for an answer")
        return live.ask(str(prompt_text))

    actions.command, actions.clear = command, pane.clear
    try:
        with printing_to(pane, ask):
            if show_header:
                for line in header(state):
                    actions.say(line)
            if first:
                print(f"> {shlex.join(first)}")
                _run(state, list(first), actions)
            code = app.run()
    finally:
        actions.command, actions.clear = plain_command, plain_clear
    # Back on the terminal: the transcript stays in its scrollback.
    transcript = pane.transcript()
    if transcript:
        sys.stdout.write(transcript if transcript.endswith("\n") else transcript + "\n")
        sys.stdout.flush()
    _end(state, actions)
    return code or 0
