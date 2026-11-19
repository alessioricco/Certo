"""session.py: the interactive session. No terminal and no model: runs and
commands are fakes, and the input loop reads prompt_toolkit's pipe input."""

from __future__ import annotations

import os
import threading
import time

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

    def run(argv, live=None):
        runs.append(argv)
        return results.pop(0) if results else None

    def command(name, argv):
        commands.append((name, argv))
        return 0

    return (
        Actions(
            run=run,
            command=command,
            say=said.append,
            clear=lambda: said.append("CLEAR"),
            start=lambda work: work(),  # the run right away, in the test's thread
        ),
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


def test_the_header_shows_the_version_model_and_folder():
    home = os.path.expanduser("~")
    lines = header(
        SessionState(folder=os.path.join(home, "certo"), model="anthropic/claude-haiku-5-5")
    )
    text = "\n".join(lines)
    assert lines[0].startswith("╭") and lines[-1].startswith("╰")
    assert f"✓ certo {__version__}" in text
    assert "model    anthropic/claude-haiku-5-5" in text
    assert f"folder   ~{os.sep}certo" in text
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
    assert said[0] == "Commands:" and any("/make-milestones [N] TASK" in line for line in said)
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


# --- a run working in its thread: live status, questions, waiting, stopping --


def _progress(**kw):
    from certo.run_progress import RunProgress

    return RunProgress(say=lambda _l: None, every_seconds=0, **kw)


def test_while_a_run_works_the_status_line_shows_it_live():
    state = _state()
    live = session.LiveRun(mode="manual", model="anthropic/claude-haiku-5-5")
    state.live = live
    progress = _progress(cost_before=0.012)
    progress.steps, progress.action = 14, "terminal pytest -q"
    live.watch(progress)
    facts, keys = status_lines(state, now=live.started + 102)
    assert facts.endswith("haiku-5-5 · step 14 · 1m 42s · $0.0120 · last: terminal pytest -q")
    assert facts[0] in session.SPINNER
    assert keys.startswith("ctrl+c stops · ask before actions: off")
    state.queued = "Add a README"
    assert status_lines(state)[1].startswith("ctrl+c stops · queued: Add a README · ")


@pytest.mark.parametrize(
    ("mode", "before"), [("escalate", "starting the ladder"), ("auto", "choosing a model")]
)
def test_on_a_ladder_or_auto_model_the_status_line_names_the_model_running_now(mode, before):
    state = _state(mode=mode)
    live = session.LiveRun(mode=mode, model="anthropic/claude-haiku-5-5")
    state.live = live
    assert status_lines(state)[0][2:].startswith(before)  # before Certo picked one
    progress = _progress()
    live.watch(progress)
    progress.model, progress.rung = "anthropic/claude-sonnet-5-5", "rung 2 of 3"
    assert status_lines(state)[0][2:].startswith("sonnet-5-5 · rung 2 of 3 · ")


def test_after_an_auto_run_the_status_line_keeps_the_model_that_ended_it():
    state = _state(mode="auto")
    assert status_lines(state)[0].startswith("model per task · auto")

    def run(argv, live):
        progress = _progress()
        live.watch(progress)
        progress.model = "sonnet-5-5"
        return _RESULT

    actions = Actions(run=run, command=lambda *_: 0, say=lambda _l: None, start=lambda w: w())
    handle(state, "Build it", actions)
    assert status_lines(state)[0].startswith("sonnet-5-5 · auto · ledger · verified")
    state.cycle("mode")  # escalate: another way of choosing, so no model yet
    assert status_lines(state)[0].startswith("model per task · escalate")


def test_during_a_run_a_message_waits_for_it_and_run_commands_wait_too():
    state = _state()
    actions, runs, commands, said = _actions([_RESULT, _RESULT])
    later: list = []
    actions.start = later.append  # the run's work, held until the test lets it end
    handle(state, "Build it", actions)
    assert state.live is not None and runs == []
    handle(state, "Add a README", actions)
    assert state.queued == "Add a README"
    handle(state, "/verify", actions)
    handle(state, "/effort high", actions)  # a switch is fine: it changes the next task
    assert commands == [] and state.effort == "high"
    assert said[-1] == "/verify waits for the run to end (Ctrl-C stops it)."
    later.pop(0)()  # the first run ends: the waiting message goes, continuing it
    assert said[-1] == "> Add a README"
    later.pop(0)()
    assert runs == [
        ["Build it"],
        ["--resume", "--project", "ledger", "--reasoning-effort", "high", "Add a README"],
    ]
    assert state.live is None and state.queued == ""


def test_ctrl_c_stops_the_run_and_its_question_and_drops_the_waiting_message():
    from certo.cancel import RunCancelled

    state = _state()
    actions, _, _, said = _actions()
    later: list = []
    actions.start = later.append
    handle(state, "Build it", actions)
    live = state.live
    handle(state, "Add a README", actions)
    asked: list = []

    def ask():
        try:
            live.ask("\n--- Confirmation required ---\nApprove? [y/N] ")
        except RunCancelled:
            asked.append("cancelled")

    thread = threading.Thread(target=ask)
    thread.start()
    _wait_for(lambda: live.question)
    assert live.question == "Approve? [y/N] "
    session._stop(state, actions)
    thread.join(timeout=5)
    assert asked == ["cancelled"] and live.cancel.is_set()
    later.pop(0)()  # the run ends, as cancelled
    assert said[-2:] == [
        "Stopped. Your next message continues it, or /new starts another.",
        "Not sent, since the run was stopped: Add a README",
    ]


def _wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_the_loop_answers_the_runs_question_at_its_prompt():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    state = _state()
    answers: list = []

    def run(argv, live):
        answers.append(live.ask("Approve? [y/N] "))
        return _RESULT

    actions = Actions(run=run, command=lambda *_: 0, say=lambda _l: None)  # a real thread
    with create_pipe_input() as pipe:

        def feed():
            _wait_for(lambda: state.live is not None and state.live.question)
            pipe.send_text("y\r")
            _wait_for(lambda: state.live is None)
            pipe.send_text("/quit\r")

        threading.Thread(target=feed, daemon=True).start()
        code = session.run_loop(
            state, actions, first=["Build it"], input=pipe, output=DummyOutput()
        )
    assert code == 0 and answers == ["y"]
    assert state.last_verdict == "verified" and state.continuing


def test_a_run_error_shows_as_its_first_line_cut_short():
    state = _state()
    long = "Conversation run failed: litellm.AuthenticationError: invalid x-api-key"
    state.note_result({"error": long + "\nConversation logs are stored at: .certo/x"})
    assert state.last_verdict == "error: Conversation run failed: litellm.Authent…"
    assert "\n" not in status_lines(state)[0]


def test_a_stopped_run_says_interrupted_with_the_sessions_time_and_its_folder():
    state = _state()
    actions, *_ = _actions([{"error": "interrupted", "workspace": "/work/hello"}])
    handle(state, "Build it", actions)
    facts = status_lines(state)[0]
    assert facts.startswith("haiku-5-5 · manual · /work/hello · interrupted · 0s")


def test_a_question_mark_asks_the_docs_even_while_a_run_works():
    state = _state()
    actions, runs, commands, _ = _actions()
    handle(state, "? what is a rung", actions)
    handle(state, "?", actions)  # a bare ? is a message, a task
    assert commands == [("ask", ["what is a rung"])]
    assert runs == [["?"]]
    state.live = session.LiveRun(mode="manual", model="m", refresh=lambda: None)
    handle(state, "?why did it pick Opus", actions)
    assert commands[-1] == ("ask", ["why did it pick Opus"])
    assert state.queued == ""


def test_make_milestones_takes_a_count_first():
    actions, runs, _, _ = _actions()
    handle(_state(), "/make-milestones 5 Build a ledger", actions)
    # A number alone is a task, not a count.
    handle(_state(), "/make-milestones 42", actions)
    assert runs == [
        ["--make-milestones", "--milestone-count", "5", "Build a ledger"],
        ["--make-milestones", "42"],
    ]
