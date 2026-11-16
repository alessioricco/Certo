"""session.py: the interactive session. No terminal and no model: runs and
commands are fakes, and the input loop reads prompt_toolkit's pipe input."""

from __future__ import annotations

import os

import pytest

from certo import __version__, cli, session
from certo.session import (
    Actions,
    SessionState,
    completions,
    first_task,
    handle,
    header,
    status_lines,
    task_argv,
)


def _state(**kw) -> SessionState:
    return SessionState(folder="/work", model="anthropic/claude-haiku-5-5", **kw)


def _actions(results=None):
    runs, commands, said = [], [], []
    results = list(results or [])

    def run(argv):
        runs.append(argv)
        return results.pop(0) if results else None

    def command(name, argv):
        commands.append((name, argv))
        return 0

    return (
        Actions(run=run, command=command, say=said.append, clear=lambda: said.append("CLEAR")),
        runs,
        commands,
        said,
    )


_RESULT = {
    "verdict": "verified",
    "project": "ledger",
    "workspace": "/work/projects/ledger",
    "usage": {"duration_seconds": 252.0, "cost": 0.03},
}


def test_the_header_shows_the_version_model_and_folder(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    lines = header(SessionState(folder="/home/me/certo", model="anthropic/claude-haiku-5-5"))
    text = "\n".join(lines)
    assert lines[0].startswith("╭") and lines[-1].startswith("╰")
    assert f"✓ certo {__version__}" in text
    assert "model    anthropic/claude-haiku-5-5" in text
    assert "folder   ~/certo" in text
    assert len({len(line) for line in lines}) == 1  # a closed box
    assert "none yet: run certo init" in "\n".join(header(SessionState(folder="/x")))


def test_the_status_line_shows_the_last_run_and_the_switches():
    state = _state()
    state.note_result(_RESULT)
    facts, switches = status_lines(state)
    assert facts == "haiku-5-5 · manual · ledger · verified · 4m 12s · $0.03"
    assert switches.startswith("ask before actions: off · mode: manual · effort: default")
    state.cycle("ask")
    state.cycle("mode")
    state.cycle("effort")
    assert status_lines(state)[1].startswith("ask before actions: on · mode: auto · effort: low")


def test_a_message_is_a_task_and_the_next_one_continues_it(monkeypatch):
    monkeypatch.delenv("CERTO_CONFIRM_MODE", raising=False)
    state = _state()
    actions, runs, _, _ = _actions([_RESULT, _RESULT])
    handle(state, "Build a ledger", actions)
    handle(state, "Add a total command", actions)
    assert runs == [["Build a ledger"], ["--resume", "--project", "ledger", "Add a total command"]]
    assert os.environ["CERTO_CONFIRM_MODE"] == "never"
    assert round(state.total_cost, 2) == 0.06
    handle(state, "/new", actions)
    handle(state, "Something else", actions)
    assert runs[-1] == ["Something else"]


def test_the_switches_become_flags_for_the_next_task(monkeypatch):
    monkeypatch.delenv("CERTO_CONFIRM_MODE", raising=False)
    state = _state(mode="escalate", effort="high", ask_before=True)
    actions, runs, _, _ = _actions()
    handle(state, "Fix the crash", actions)
    assert runs == [["--escalate", "--reasoning-effort", "high", "Fix the crash"]]
    assert os.environ["CERTO_CONFIRM_MODE"] == "always"
    assert task_argv(_state(model_override="sonnet"), "x") == ["--model", "sonnet", "x"]
    assert task_argv(_state(mode="auto"), "x") == ["--auto-model", "x"]


def test_commands_run_in_the_last_runs_project():
    state = _state()
    actions, runs, commands, said = _actions([_RESULT])
    handle(state, "Build a ledger", actions)
    for line in (
        "/verify",
        "/report it hung",
        "/checkpoints",
        "/rollback 2",
        "/ask what is unchanged?",
    ):
        handle(state, line, actions)
    where = "/work/projects/ledger"
    assert commands == [
        ("verify", [where]),
        ("report", [where, "--note", "it hung"]),
        ("checkpoints", [where]),
        ("rollback", ["2", where]),
        ("ask", ["what is unchanged?"]),
    ]


def test_milestone_commands_and_switch_commands():
    state = _state()
    actions, runs, _, said = _actions()
    handle(state, "/make-milestones Build a ledger", actions)
    handle(state, "/milestones plan.md", actions)
    handle(state, "/mode auto", actions)
    handle(state, "/effort medium", actions)
    assert runs == [["--make-milestones", "Build a ledger"], ["--milestones", "plan.md"]]
    assert (state.mode, state.effort) == ("auto", "medium")
    handle(state, "/mode fast", actions)
    handle(state, "/rollback two", actions)
    handle(state, "/nope", actions)
    assert said[-3:] == [
        "Usage: /mode manual|auto|escalate",
        "Usage: /rollback N (the number from /checkpoints)",
        "Unknown command /nope. /help lists them.",
    ]


def test_help_clear_and_quit():
    actions, _, _, said = _actions()
    assert handle(_state(), "/help", actions)
    assert said[0] == "Commands:" and any("/make-milestones TASK" in line for line in said)
    assert handle(_state(), "/clear", actions) and said[-1] == "CLEAR"
    assert handle(_state(), "/quit", actions) is False
    assert handle(_state(), "/exit", actions) is False


def test_slash_completes_the_commands():
    assert [name for name, _ in completions("/re")] == ["/resume", "/report"]
    assert completions("hello") == [] and completions("/ask how") == []


def test_the_input_loop_reads_lines_and_keys():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    state = _state()
    actions, runs, _, said = _actions()
    with create_pipe_input() as pipe:
        # Shift+Tab (ESC [ Z) turns on "ask before actions"; then a task; then /quit.
        pipe.send_text("\x1b[ZBuild it\r/quit\r")
        code = session.run_loop(state, actions, input=pipe, output=DummyOutput())
    assert code == 0
    assert state.ask_before is True
    assert runs == [["Build it"]]
    assert said[0].startswith("╭")


def test_first_task_drops_the_interactive_flag():
    assert first_task(["-i", "Build it", "--project", "x"]) == ["Build it", "--project", "x"]


@pytest.mark.parametrize(
    ("argv", "first"),
    [
        ([], []),
        (["-i"], []),
        (["-i", "Build it", "--project", "x"], ["Build it", "--project", "x"]),
        (["Build it", "--interactive"], ["Build it"]),
    ],
)
def test_in_a_terminal_certo_opens_the_session(monkeypatch, argv, first):
    seen = []
    monkeypatch.setattr(session, "is_terminal", lambda: True)
    monkeypatch.setattr(cli, "_session", lambda f: seen.append(f) or 0)
    assert cli.main(argv) == 0
    assert seen == [first]


def test_without_a_terminal_or_with_json_the_plain_run_stays(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_session", lambda f: pytest.fail("no session"))
    monkeypatch.setattr(session, "is_terminal", lambda: False)
    with pytest.raises(SystemExit):
        cli.main([])
    monkeypatch.setattr(session, "is_terminal", lambda: True)
    monkeypatch.setattr(cli, "_run_task_command", lambda args, parser, holder: 0)
    assert cli.main(["-i", "Build it", "--json"]) == 0
