"""The interactive session: `certo` alone in a terminal, or `certo -i "task"`
(docs/history/interactive-session.md; DECISIONS.md, 2026-11-16).

Full screen, as the common coding-agent terminals are (session_screen.py):
the transcript in a scrollable pane, an input box with `/` commands, and a
status line with the switches. A message is a task: the first one new, the
next ones continuing it (`--resume` in its project) until `/new`.

A run works in its own thread and prints what `certo "task"` prints, into
the pane. The input box stays: the status line shows the run live (the
model running now, step, time, cost, last action), the run's questions are
answered there, a message typed meanwhile waits for the run to end, and
Ctrl-C stops the run after its current step (the runner's cancel token,
cancel.py).

Everything but the screen is plain functions on `SessionState`, tested
without a terminal. Built on prompt_toolkit, already a dependency.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

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
# What can be typed while a run works: commands that start no run and
# leave the project alone. The others wait for the run to end.
DURING_RUN = frozenset({"/help", "/model", "/mode", "/effort", "/ask", "/clear", "/quit", "/exit"})
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
KEYS = (
    ("shift+tab", "ask before actions"),
    ("ctrl+t", "mode"),
    ("ctrl+o", "effort"),
)


class LiveRun:
    """A run working in its thread: what the status line shows, its
    questions to the prompt, and its cancel token."""

    def __init__(
        self,
        mode: str = "manual",
        model: str = "",
        refresh: Callable[[], None] = lambda: None,
        label: str = "",
    ) -> None:
        self.mode = mode  # the run's own mode and model: switches change the next task
        self.model = model
        self.label = label  # a command working in the thread ("/verify"), not a run
        self.started = time.monotonic()
        self.progress: Any = None  # run_progress.RunProgress, once the run made it
        self.cancel = threading.Event()
        self.question = ""  # a question of the run's, waiting at the prompt
        self.thread: threading.Thread | None = None
        self._answers: queue.Queue[str | None] = queue.Queue()
        self._refresh = refresh

    def watch(self, progress: Any) -> None:
        """The run's progress, to read for the status line."""
        self.progress = progress

    def ask(self, prompt: str) -> str:
        """In the run's thread: ask `prompt` at the session's prompt and
        wait for the answer. A stopped run raises `RunCancelled`."""
        from .cancel import RunCancelled

        lines = prompt.strip("\n").split("\n")
        for line in lines[:-1]:
            print(line, flush=True)
        self.question = lines[-1].rstrip() + " "
        if self.cancel.is_set():  # stopped before the question was shown
            self.question = ""
            raise RunCancelled()
        self._refresh()
        answer = self._answers.get()
        self.question = ""
        self._refresh()
        if answer is None:
            raise RunCancelled()
        return answer

    def answer(self, text: str | None) -> None:
        self._answers.put(text)

    def stop(self) -> None:
        """Stop the run after its current step, and any question it asks."""
        self.cancel.set()
        if self.question:
            self.answer(None)

    def model_now(self) -> str:
        """The model working now, for the status line."""
        if self.progress is not None and self.progress.model:
            return _short_model(self.progress.model)
        if self.mode == "auto":
            return "choosing a model"
        if self.mode == "escalate":
            return "starting the ladder"
        return _short_model(self.model)


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
    last_model: str = ""  # the model that ended the last auto or escalate run
    live: LiveRun | None = None  # the run working now
    queued: str = ""  # a message typed during the run, sent when it ends
    runs: list[LiveRun] = field(default_factory=list)  # every run started, for the tests

    def cycle(self, switch: str) -> None:
        if switch == "ask":
            self.ask_before = not self.ask_before
        elif switch == "mode":
            self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])
        elif switch == "effort":
            self.effort = EFFORTS[(EFFORTS.index(self.effort) + 1) % len(EFFORTS)]

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.last_model = ""
        self.mode = mode

    def note_result(self, result: dict | None) -> None:
        """Keep the last run's verdict, time and cost for the status line."""
        if not result:
            return
        self.project = result.get("project") or self.project
        self.workspace = result.get("workspace") or self.workspace
        # An error can be long and many lines: its first line, cut short.
        error = (result.get("error") or "").strip().split("\n")[0]
        if error == "interrupted":  # stopped, not failed
            error_text = error
        else:
            error_text = _cut(f"error: {error}", 48) if error else ""
        self.last_verdict = result.get("verdict") or error_text
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


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def status_lines(state: SessionState, now: float | None = None) -> tuple[str, str]:
    """The two lines under the prompt: the facts (the run's, live, while
    one works), then the switches."""
    switches = (
        f"ask before actions: {'on' if state.ask_before else 'off'} · mode: {state.mode} · "
        f"effort: {state.effort}   (shift+tab, ctrl+t, ctrl+o)"
    )
    live = state.live
    if live is not None:
        return _live_facts(live, time.monotonic() if now is None else now), (
            "ctrl+c stops"
            + (f" · queued: {_cut(state.queued, 30)}" if state.queued else "")
            + " · "
            + switches
        )
    if state.mode == "manual":
        model = _short_model(state.model_override or state.model)
    else:  # Certo picks the model per task: the one that ended the last run
        model = _short_model(state.last_model) if state.last_model else "model per task"
    facts = [model, state.mode, state.project or _home(state.workspace or state.folder)]
    if state.last_verdict:
        facts += [state.last_verdict, _duration(state.last_seconds)]
    if state.total_cost:
        facts.append(f"${state.total_cost:.2f}")
    return " · ".join(facts), switches


def _live_facts(live: LiveRun, now: float) -> str:
    """The status line while a run works: the model running now first."""
    spin = SPINNER[int(now * 8) % len(SPINNER)]
    if live.label:
        return f"{spin} {live.label} · {_duration(now - live.started)}"
    facts = [f"{spin} {live.model_now()}"]
    progress = live.progress
    if progress is not None:
        facts += [f for f in (progress.rung, progress.where, progress.fix, progress.checks) if f]
        if progress.steps:
            facts.append(f"step {progress.steps}")
    facts.append(_duration(now - live.started))
    if progress is not None:
        facts.append(f"${progress.live_cost():.4f}")
        if progress.action:
            facts.append(f"last: {progress.action}")
    return " · ".join(facts)


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
        "?QUESTION asks Certo's docs, as /ask; also at a run's questions.",
    ]
    return lines


@dataclass
class Actions:
    """What the session does, given by the caller (cli.py; fakes in tests)."""

    run: Callable[[list[str], LiveRun], dict | None]  # certo argv -> the run's JSON result
    command: Callable[[str, list[str]], int]  # a subcommand ("verify", ...) and its argv
    say: Callable[[str], None] = print
    clear: Callable[[], None] = lambda: print("\033[2J\033[H", end="")
    # Starts a run's work: in a thread (tests: right away, in theirs).
    start: Callable[[Callable[[], None]], threading.Thread | None] = lambda work: _in_thread(work)
    refresh: Callable[[], None] = lambda: None  # redraw the prompt and status line


def _in_thread(work: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=work, name="certo-session-run", daemon=True)
    thread.start()
    return thread


def handle(state: SessionState, line: str, actions: Actions) -> bool:
    """Do what one input line asks. False when the session should end."""
    line = line.strip()
    if not line:
        return True
    if line.startswith("?") and line[1:].strip():
        # A question about Certo, as /ask; also while a run works.
        actions.command("ask", [line[1:].strip()])
        return True
    if not line.startswith("/"):
        if state.live is not None:
            replaced = bool(state.queued)
            state.queued = line
            actions.say(
                ("Replaced the waiting message: " if replaced else "Waiting for the run: ")
                + "it is sent when the run ends (Ctrl-C stops the run)."
            )
            return True
        _run(state, task_argv(state, line), actions)
        return True
    name, _, rest = line.partition(" ")
    rest = rest.strip()
    if state.live is not None and name not in DURING_RUN and any(c.name == name for c in COMMANDS):
        actions.say(f"{name} waits for the run to end (Ctrl-C stops it).")
        return True
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
            state.set_mode("manual")
        actions.say(f"Model for the next tasks: {rest or state.model or 'the configured one'}.")
    elif name == "/mode":
        if rest not in MODES:
            actions.say(f"Usage: /mode {'|'.join(MODES)}")
        else:
            state.set_mode(rest)
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
    """Start a run: its work goes on in a thread while the prompt stays."""
    from .cancel import cancel_token

    os.environ["CERTO_CONFIRM_MODE"] = "always" if state.ask_before else "never"
    live = LiveRun(
        mode=state.mode,
        model=state.model_override or state.model,
        refresh=lambda: actions.refresh(),
    )
    state.live = live
    state.runs.append(live)

    def work() -> None:
        result = None
        try:
            with cancel_token(live.cancel):
                result = actions.run(argv, live)
        except Exception as exc:  # noqa: BLE001 - said, and the session goes on
            actions.say(f"Error: {exc}")
        finally:
            _finished(state, live, result, actions)

    live.thread = actions.start(work)


def _finished(state: SessionState, live: LiveRun, result: dict | None, actions: Actions) -> None:
    """A run ended: keep its result, then send the message that waited."""
    state.live = None
    if live.mode != "manual" and live.progress is not None and live.progress.model:
        state.last_model = live.progress.model
    state.note_result(result)
    if result is not None:
        state.continuing = True  # the next message continues this task
        if not state.last_seconds:  # a stopped run has no usage: the session's clock
            state.last_seconds = time.monotonic() - live.started
    waiting, state.queued = state.queued, ""
    if live.cancel.is_set():
        actions.say("Stopped. Your next message continues it, or /new starts another.")
        if waiting:
            actions.say(f"Not sent, since the run was stopped: {waiting}")
    elif waiting:
        actions.say(f"> {waiting}")
        _run(state, task_argv(state, waiting), actions)
    actions.refresh()


def _stop(state: SessionState, actions: Actions) -> None:
    live = state.live
    if live is not None and not live.cancel.is_set():
        actions.say("Stopping the run after its current step...")
        live.stop()


def _end(state: SessionState, actions: Actions) -> None:
    """The session ends: a run still working is stopped first."""
    while (live := state.live) is not None:
        _stop(state, actions)
        if live.thread is None:
            return
        live.thread.join()


def completions(text: str) -> Iterable[tuple[str, str]]:
    """(command, help) for the commands starting with `text` (a `/` word)."""
    if not text.startswith("/") or " " in text:
        return []
    return [(c.name, c.help) for c in COMMANDS if c.name.startswith(text)]


def run_loop(
    state: SessionState,
    actions: Actions,
    *,
    show_header: bool = True,
    first: Sequence[str] = (),
    input=None,
    output=None,
) -> int:
    """The session's screen (session_screen.py). `first`: certo arguments
    to run as the first task. `input`/`output`: prompt_toolkit's, for tests."""
    from .session_screen import run_screen

    return run_screen(
        state, actions, show_header=show_header, first=first, input=input, output=output
    )


def first_task(argv: Sequence[str]) -> list[str]:
    """`certo -i ...`'s arguments without -i/--interactive: the first run."""
    return [a for a in argv if a not in ("-i", "--interactive")]


def session_main(
    run: Callable[[list[str], LiveRun], dict | None],
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
    return run_loop(state, Actions(run=run, command=command), first=list(first))


def is_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
