"""session_screen.py: the session's full screen. No terminal: the screen
reads prompt_toolkit's pipe input and draws on its dummy output."""

from __future__ import annotations

import builtins
import io
import logging
import sys
import threading
import time

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from certo import session
from certo.session_screen import OutputPane, printing_to, without_controls


def test_the_pane_keeps_colors_and_drops_other_control_codes():
    pane = OutputPane()
    pane.write("\x1b[?2004lplain \x1b[32mgreen\x1b[0m\n50%\r100%\npartial")
    assert pane.line_count() == 3
    fragments = pane.fragments()
    text = "".join(t for _, t in fragments)
    assert text == "plain green\n100%\npartial"
    assert ("ansigreen", "green") in fragments
    # The printed-back transcript is what was written, codes and all.
    assert pane.transcript().startswith("\x1b[?2004lplain")
    assert without_controls("\x1b]0;title\x07ok\x07") == "ok"


def test_the_pane_scrolls_within_its_lines_and_clear_empties_the_screen():
    pane = OutputPane()
    pane.write("".join(f"line {i}\n" for i in range(10)))
    pane.scroll_by(4)
    assert pane.scroll == 4
    pane.scroll_by(100)
    assert pane.scroll == 9
    pane.scroll_by(-100)
    assert pane.scroll == 0
    pane.clear()
    assert pane.line_count() == 0 and "line 9" in pane.transcript()


def test_while_the_screen_is_up_prints_logs_and_input_go_through_it():
    pane = OutputPane()
    handler = logging.StreamHandler(sys.stderr)
    logger = logging.getLogger("certo-test-screen")
    logger.addHandler(handler)
    try:
        with printing_to(pane, lambda prompt: f"answer to {prompt}"):
            print("printed")
            logger.warning("logged")
            assert builtins.input("Go ahead? ") == "answer to Go ahead? "
        assert sys.stdout is not pane and handler.stream is sys.stderr
    finally:
        logger.removeHandler(handler)
    assert "printed\n" in pane.transcript() and "logged\n" in pane.transcript()


def _wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_command_runs_in_a_thread_and_its_question_is_asked_in_the_box(monkeypatch):
    state = session.SessionState(folder="/work", workspace="/work/p")
    asked = []

    def command(name, argv):
        asked.append((name, argv, input("Go ahead? [y/N] ")))
        return 0

    actions = session.Actions(run=lambda argv, live: None, command=command, say=lambda _l: None)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    with create_pipe_input() as pipe:

        def feed():
            pipe.send_text("/rollback 2\r")
            _wait_for(lambda: state.live is not None and state.live.question)
            assert state.live.label == "/rollback"
            pipe.send_text("n\r")
            _wait_for(lambda: state.live is None)
            pipe.send_text("/quit\r")

        threading.Thread(target=feed, daemon=True).start()
        code = session.run_loop(state, actions, input=pipe, output=DummyOutput())
    assert code == 0
    assert asked == [("rollback", ["2", "/work/p"], "n")]
    # Back on the terminal: the transcript, with the answer, in the scrollback.
    printed = out.getvalue()
    assert "> /rollback 2\n" in printed and "Go ahead? [y/N] n\n" in printed
