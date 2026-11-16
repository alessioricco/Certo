"""The interactive session: `certo` alone in a terminal, or `certo -i "task"`
(docs/history/interactive-session.md; DECISIONS.md, 2026-11-16).

Inline, as the common coding-agent terminals are: a header printed once,
then a prompt with `/` commands and, below it, a status line with the
switches. A message is a task: the first one new, the next ones
continuing it (`--resume` in its project) until `/new`. A run prints what
`certo "task"` prints, with no prompt on screen; Ctrl-C stops it and comes
back to the prompt.

Everything but the input loop is plain functions on `SessionState`,
tested without a terminal. Built on prompt_toolkit, already a dependency.
"""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from . import __version__

MODES = ("manual", "auto", "escalate")
EFFORTS = ("default", "low", "medium", "high")
TAGLINE = "the coding agent that checks its own work"


@dataclass(frozen=True)
class Command:
    name: str
    args: str
    help: str


COMMANDS: tuple[Command, ...] = (
    Command("/help", "", "the commands and the keys"),
    Command("/new", "", "the next message is a new task"),
    Command("/resume", "", "continue the last run here"),
    Command("/milestones", "FILE", "run a task file milestone by milestone"),
    Command("/make-milestones", "TASK", "plan the task in milestones, then run them"),
    Command("/verify", "", "check the project, no agent"),
    Command("/ask", "QUESTION", "answer from Certo's docs"),
    Command("/report", "[NOTE]", "write the last run's problems to a file"),
    Command("/checkpoints", "", "list the checkpoints"),
    Command("/rollback", "N", "go back to checkpoint N (asks first)"),
    Command("/model", "NAME", "use this model for the next tasks"),
    Command("/mode", "manual|auto|escalate", "the model mode"),
    Command("/effort", "default|low|medium|high", "the reasoning effort"),
    Command("/clear", "", "clear the screen"),
    Command("/quit", "", "end the session (also /exit, Ctrl-D)"),
)
KEYS = (
    ("shift+tab", "ask before actions"),
    ("ctrl+t", "mode"),
    ("ctrl+o", "effort"),
)


@dataclass
class SessionState:
    folder: str  # where the session started
    model: str = ""  # the configured model, for the header and status line
    model_override: str = ""  # /model NAME
    project: str | None = None  # the task's project, once a run named one
    workspace: str = ""  # the last run's project folder
    continuing: bool = False  # the next message continues the last task
    ask_before: bool = False
    mode: str = "manual"
    effort: str = "default"
    last_verdict: str = ""
    last_seconds: float = 0.0
    total_cost: float = 0.0

    def cycle(self, switch: str) -> None:
        if switch == "ask":
            self.ask_before = not self.ask_before
        elif switch == "mode":
            self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        elif switch == "effort":
            self.effort = EFFORTS[(EFFORTS.index(self.effort) + 1) % len(EFFORTS)]

    def note_result(self, result: dict | None) -> None:
        """Keep the last run's verdict, time and cost for the status line."""
        if not result:
            return
        self.project = result.get("project") or self.project
        self.workspace = result.get("workspace") or self.workspace
        self.last_verdict = result.get("verdict") or result.get("error") or ""
        usage = result.get("usage") or {}
        self.last_seconds = usage.get("duration_seconds") or 0.0
        self.total_cost += usage.get("cost") or 0.0


def _short_model(model: str) -> str:
    name = model.split("/", 1)[-1]
    return name.removeprefix("claude-") if name else "no model"


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest:02d}s" if minutes else f"{rest}s"


def _home(path: str, limit: int = 48) -> str:
    """`path` with the home folder as `~`, and cut from the left past `limit`."""
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        path = "~" + path[len(home) :]
    return path if len(path) <= limit else "…" + path[-(limit - 1) :]


def header(state: SessionState) -> list[str]:
    """The box printed once when the session starts."""
    model = state.model or "none yet: run certo init"
    rows = [
        f"✓ certo {__version__}",
        f"  {TAGLINE}",
        "",
        f"  model    {model}",
        f"  folder   {_home(state.folder)}",
        "  /help for commands · shift+tab: switches",
    ]
    width = max(len(r) for r in rows) + 2
    return (
        ["╭" + "─" * width + "╮"]
        + [f"│ {r.ljust(width - 1)}│" for r in rows]
        + ["╰" + "─" * width + "╯"]
    )


def status_lines(state: SessionState) -> tuple[str, str]:
    """The two lines under the prompt: the facts, then the switches."""
    model = state.model_override or state.model
    facts = [_short_model(model), state.mode, state.project or _home(state.folder)]
    if state.last_verdict:
        facts += [state.last_verdict, _duration(state.last_seconds)]
    if state.total_cost:
        facts.append(f"${state.total_cost:.2f}")
    switches = (
        f"ask before actions: {'on' if state.ask_before else 'off'} · mode: {state.mode} · "
        f"effort: {state.effort}   (shift+tab, ctrl+t, ctrl+o)"
    )
    return " · ".join(facts), switches


def task_argv(state: SessionState, text: str, extra: Sequence[str] = ()) -> list[str]:
    """The `certo` arguments for a message: a new task, or the last one
    continued, with the switches as flags."""
    argv: list[str] = []
    if state.continuing:
        argv.append("--resume")
    if state.project:
        argv += ["--project", state.project]
    if state.mode == "auto":
        argv.append("--auto-model")
    elif state.mode == "escalate":
        argv.append("--escalate")
    elif state.model_override:
        argv += ["--model", state.model_override]
    if state.effort != "default":
        argv += ["--reasoning-effort", state.effort]
    return argv + list(extra) + ([text] if text else [])


def help_lines() -> list[str]:
    lines = ["Commands:"]
    lines += [f"  {(c.name + ' ' + c.args).strip():<36} {c.help}" for c in COMMANDS]
    lines += ["", "Keys:"]
    lines += [f"  {k:<36} {what}" for k, what in KEYS]
    lines += [
        "",
        "A message is a task. The next ones continue it, until /new.",
    ]
    return lines


@dataclass
class Actions:
    """What the session does, given by the caller (cli.py; fakes in tests)."""

    run: Callable[[list[str]], dict | None]  # certo argv -> the run's JSON result
    command: Callable[[str, list[str]], int]  # a subcommand ("verify", ...) and its argv
    say: Callable[[str], None] = print
    clear: Callable[[], None] = lambda: print("\033[2J\033[H", end="")


def handle(state: SessionState, line: str, actions: Actions) -> bool:
    """Do what one input line asks. False when the session should end."""
    line = line.strip()
    if not line:
        return True
    if not line.startswith("/"):
        _run(state, task_argv(state, line), actions)
        return True
    name, _, rest = line.partition(" ")
    rest = rest.strip()
    here = [state.workspace] if state.workspace else []
    if name in ("/quit", "/exit"):
        return False
    if name == "/help":
        for out in help_lines():
            actions.say(out)
    elif name == "/new":
        state.continuing = False
        state.project = None
        state.workspace = ""
        actions.say("The next message is a new task.")
    elif name == "/resume":
        state.continuing = True
        _run(state, task_argv(state, rest), actions)
    elif name == "/milestones":
        if not rest:
            actions.say("Usage: /milestones FILE")
        else:
            state.continuing = False
            _run(state, task_argv(state, rest, ["--milestones"]), actions)
    elif name == "/make-milestones":
        if not rest:
            actions.say("Usage: /make-milestones TASK")
        else:
            state.continuing = False
            _run(state, task_argv(state, rest, ["--make-milestones"]), actions)
    elif name == "/verify":
        actions.command("verify", here)
    elif name == "/ask":
        if not rest:
            actions.say("Usage: /ask QUESTION")
        else:
            actions.command("ask", [rest])
    elif name == "/report":
        actions.command("report", here + (["--note", rest] if rest else []))
    elif name == "/checkpoints":
        actions.command("checkpoints", here)
    elif name == "/rollback":
        if not rest.isdigit():
            actions.say("Usage: /rollback N (the number from /checkpoints)")
        else:
            actions.command("rollback", [rest, *here])
    elif name == "/model":
        state.model_override = rest
        if rest and state.mode != "manual":
            state.mode = "manual"
        actions.say(f"Model for the next tasks: {rest or state.model or 'the configured one'}.")
    elif name == "/mode":
        if rest not in MODES:
            actions.say(f"Usage: /mode {'|'.join(MODES)}")
        else:
            state.mode = rest
    elif name == "/effort":
        if rest not in EFFORTS:
            actions.say(f"Usage: /effort {'|'.join(EFFORTS)}")
        else:
            state.effort = rest
    elif name == "/clear":
        actions.clear()
    else:
        actions.say(f"Unknown command {name}. /help lists them.")
    return True


def _run(state: SessionState, argv: list[str], actions: Actions) -> None:
    os.environ["CERTO_CONFIRM_MODE"] = "always" if state.ask_before else "never"
    result = actions.run(argv)
    state.note_result(result)
    if result is not None:
        state.continuing = True  # the next message continues this task


def completions(text: str) -> Iterable[tuple[str, str]]:
    """(command, help) for the commands starting with `text` (a `/` word)."""
    if not text.startswith("/") or " " in text:
        return []
    return [(c.name, c.help) for c in COMMANDS if c.name.startswith(text)]


def run_loop(
    state: SessionState, actions: Actions, *, show_header: bool = True, input=None, output=None
) -> int:
    """The input loop. `input`/`output`: prompt_toolkit's, for tests."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.key_binding import KeyBindings

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            word = document.text_before_cursor
            for name, meta in completions(word):
                yield Completion(name, start_position=-len(word), display_meta=meta)

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

    def toolbar() -> str:
        facts, switches = status_lines(state)
        return f" {facts}\n {switches}"

    session = PromptSession(
        "> ",
        completer=SlashCompleter(),
        complete_while_typing=True,
        bottom_toolbar=toolbar,
        key_bindings=keys,
        input=input,
        output=output,
    )
    if show_header:
        for line in header(state):
            actions.say(line)
    while True:
        try:
            line = session.prompt()
        except KeyboardInterrupt:
            continue  # Ctrl-C at the prompt clears the line
        except EOFError:
            return 0
        try:
            if not handle(state, line, actions):
                return 0
        except KeyboardInterrupt:
            actions.say("\nStopped. Your next message continues it, or /new starts another.")


def first_task(argv: Sequence[str]) -> list[str]:
    """`certo -i ...`'s arguments without -i/--interactive: the first run."""
    return [a for a in argv if a not in ("-i", "--interactive")]


def session_main(
    run: Callable[[list[str]], dict | None],
    command: Callable[[str, list[str]], int],
    first: Sequence[str] = (),
) -> int:
    """Start the session in the current folder; run `first` (certo
    arguments) as its first task when given."""
    from .config import ConfigError, load_config

    state = SessionState(folder=os.getcwd())
    try:
        cfg = load_config()
        state.model = cfg.model
        state.mode = cfg.model_selection if cfg.model_selection in MODES else "manual"
        state.ask_before = cfg.confirm_mode == "always"
    except ConfigError:
        pass
    actions = Actions(run=run, command=command)
    if first:
        for line in header(state):
            actions.say(line)
        actions.say(f"> {shlex.join(first)}")
        _run(state, list(first), actions)
        return run_loop(state, actions, show_header=False)
    return run_loop(state, actions)


def is_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
