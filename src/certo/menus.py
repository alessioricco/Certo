"""Arrow-key menus for `certo init` and `certo init models`, on a real
terminal: one choice (`choose`, `confirm`) with prompt_toolkit's own
`choice()`, and a checklist (`checklist`) built from its application,
key-binding and layout pieces, since prompt_toolkit's only multi-select
is a full-screen dialog. `init_cmd.Prompter` uses them when stdin and
stdout are a terminal (and TERM isn't "dumb"); otherwise, and in every
test, the numbered questions are asked instead.

The checklist's state is `ChecklistState`, plain Python, so its keys are
tested without a terminal; only `checklist()` draws it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

HELP = "↑↓ move · Space select · Enter done, or open a line under More · ? ask Certo's docs"
DOCS_HINT = "? ask Certo's docs"
DOCS_URL = "https://github.com/alessioricco/certo/blob/main/docs/README.md"
# What a menu returns when "?" is pressed: never a valid index.
ASK = "?"


def answer_from_docs(question: str) -> None:
    """`certo ask QUESTION`, from a menu or a question; a failure prints one
    line (no model set up yet, say) and the menu goes on."""
    from .ask_cmd import _ask_config, ask_main
    from .config import ConfigError

    try:
        _ask_config()
    except ConfigError:
        # The usual case during the first `certo init`: no model yet.
        print(f"certo ask needs a model, and none is set up yet. The docs: {DOCS_URL}")
        return
    try:
        ask_main([question])
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001 - a help question must not end the setup
        print(f"certo ask failed: {exc}", file=sys.stderr)


def docs_question(read: Callable[[str], str] = input) -> None:
    """After "?" in a menu: ask for the question, then answer it."""
    try:
        question = read("Your question about Certo (Enter to go back): ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if question:
        answer_from_docs(question)


def available() -> bool:
    """Whether menus can be drawn: an interactive terminal on both ends."""
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def choose(question: str, options: list[str], default: int = 0) -> int:
    """One of `options`, by index. "?" asks Certo's docs, then shows the
    menu again. Ctrl-C raises KeyboardInterrupt."""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import choice

    keys = KeyBindings()

    @keys.add("?")
    def _question(event) -> None:
        event.app.exit(result=ASK)

    while True:
        picked = choice(
            message=question,
            options=[(i, option) for i, option in enumerate(options)],
            default=default,
            symbol="▸",
            bottom_toolbar=DOCS_HINT,
            key_bindings=keys,
        )
        if picked != ASK:
            return picked
        docs_question()


def confirm(question: str, default: bool = True) -> bool:
    return choose(question, ["Yes", "No"], 0 if default else 1) == 0


@dataclass
class Row:
    """A line of a checklist: a group `header` (not selectable), an `item`
    (Space turns it on or off), or an `action` (Enter runs it)."""

    kind: str
    label: str
    note: str = ""
    checked: bool = False


@dataclass
class ChecklistState:
    rows: list[Row]
    position: int = field(default=-1)

    def __post_init__(self) -> None:
        if self.position < 0:
            self.position = self._selectable()[0]

    def _selectable(self) -> list[int]:
        return [i for i, row in enumerate(self.rows) if row.kind != "header"]

    def move(self, step: int) -> None:
        selectable = self._selectable()
        index = selectable.index(self.position) + step
        self.position = selectable[max(0, min(index, len(selectable) - 1))]

    def toggle(self) -> None:
        row = self.rows[self.position]
        if row.kind == "item":
            row.checked = not row.checked

    def enter(self) -> int | None:
        """The row index of the action to run, or None: the list is done."""
        return self.position if self.rows[self.position].kind == "action" else None

    def lines(self) -> list[tuple[str, str]]:
        """(style, text) fragments to draw."""
        out: list[tuple[str, str]] = []
        for i, row in enumerate(self.rows):
            pointer = "▸ " if i == self.position else "  "
            if row.kind == "header":
                out.append(("bold", f"  {row.label}\n"))
                continue
            mark = ("[x] " if row.checked else "[ ] ") if row.kind == "item" else ""
            style = "reverse" if i == self.position else ""
            out.append((style, f"{pointer}{mark}{row.label}"))
            if row.note:
                out.append(("fg:ansibrightblack", f"  {row.note}"))
            out.append(("", "\n"))
        out.append(("fg:ansibrightblack", f"\n{HELP}\n"))
        return out


def checklist(question: str, state: ChecklistState) -> int | None:
    """Draw `state` until Enter. Returns the action row to run, or None
    when the list is done; `state.rows[i].checked` holds the choice.
    "?" asks Certo's docs, then draws it again. Ctrl-C raises
    KeyboardInterrupt."""
    while True:
        picked = _checklist_once(question, state)
        if picked != ASK:
            return picked
        docs_question()


def _checklist_once(question: str, state: ChecklistState) -> int | str | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    keys = KeyBindings()

    @keys.add("up")
    def _up(event) -> None:
        state.move(-1)

    @keys.add("down")
    def _down(event) -> None:
        state.move(1)

    @keys.add(" ")
    def _space(event) -> None:
        state.toggle()

    @keys.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=state.enter())

    @keys.add("?")
    def _question(event) -> None:
        event.app.exit(result=ASK)

    @keys.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(exception=KeyboardInterrupt())

    body = HSplit(
        [
            Window(FormattedTextControl([("bold", question + "\n")]), dont_extend_height=True),
            Window(
                FormattedTextControl(lambda: state.lines()),
                always_hide_cursor=True,
                dont_extend_height=True,
            ),
        ]
    )
    app = Application(layout=Layout(body), key_bindings=keys, full_screen=False)
    return app.run()
