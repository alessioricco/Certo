"""slow_tests.py: timing the agent's own test runs, and the one note when
one is slow for the time budget. No model call."""

from __future__ import annotations

import time as real_time
from types import SimpleNamespace

import pytest

from certo import slow_tests


class _Conversation:
    paused = False

    def pause(self):
        self.paused = True


def _action(event_id: str, command: str, *, source: str = "agent", is_input: bool = False):
    action = SimpleNamespace(command=command, is_input=is_input)
    return type("ActionEvent", (), {"id": event_id, "source": source, "action": action})()


def _observation(action_id: str):
    return type("ObservationEvent", (), {"action_id": action_id})()


@pytest.mark.parametrize(
    "command",
    [
        "npm test",
        "npx playwright test --project=desktop",
        "uv run pytest -q",
        "go test ./...",
        "cargo test",
        "npm run test:e2e",
        "python -m unittest discover",
        "bundle exec rspec spec/models",
        "dotnet test",
    ],
)
def test_test_commands_are_recognised(command):
    assert slow_tests.looks_like_test_command(command)


@pytest.mark.parametrize(
    "command", ["npm install", "ls -la", "python app.py", "cat contest.txt", "git status"]
)
def test_other_commands_are_not(command):
    assert not slow_tests.looks_like_test_command(command)


def test_the_threshold_is_a_tenth_of_the_budget_but_at_least_a_minute():
    assert slow_tests.slow_threshold(1800) == 180
    assert slow_tests.slow_threshold(300) == 60


def test_a_slow_test_run_makes_the_note_due_once(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(slow_tests.time, "monotonic", lambda: clock["now"])
    watch = slow_tests.new_watch(1800)

    watch(_action("a1", "npx playwright test"))
    clock["now"] = 100.0  # under 180 s: no note
    watch(_observation("a1"))
    assert not watch.due

    watch(_action("a2", "npx playwright test"))
    clock["now"] = 640.0  # 540 s, as in the field: a note
    watch(_observation("a2"))
    assert watch.due
    assert watch.slow == ("npx playwright test", 540.0)


def test_slow_commands_that_are_not_tests_input_or_from_the_user_are_ignored(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(slow_tests.time, "monotonic", lambda: clock["now"])
    watch = slow_tests.new_watch(600)
    watch(_action("a1", "npm install"))
    watch(_action("a2", "npm test", source="user"))
    watch(_action("a3", "npm test", is_input=True))
    clock["now"] = 500.0
    for event_id in ("a1", "a2", "a3", "unknown"):
        watch(_observation(event_id))
    assert not watch.due


def test_no_watch_without_a_time_budget():
    assert slow_tests.new_watch(float("inf")) is None
    assert slow_tests.new_watch(0) is None


def test_the_note_names_the_command_the_share_and_the_time_left():
    conversation = _Conversation()
    watch = slow_tests.new_watch(1800)
    slow_tests.attach(conversation, watch)
    watch.record("npx playwright test", 540)

    note = slow_tests.take_note(conversation, deadline=1000.0, now=0.0)

    assert "about 9 minute(s), 30% of the time budget" in note
    assert "about 16 minute(s) are left" in note
    assert "`npx playwright test`" in note
    assert "run only the tests for what you changed" in note
    assert "costs the whole timeout" in note
    # Once per conversation, even if another slow run follows.
    watch.record("npx playwright test", 600)
    assert slow_tests.take_note(conversation, deadline=1000.0, now=1.0) is None


def test_no_note_after_the_deadline():
    conversation = _Conversation()
    watch = slow_tests.new_watch(1800)
    slow_tests.attach(conversation, watch)
    watch.record("npm test", 600)
    assert slow_tests.take_note(conversation, deadline=10.0, now=20.0) is None


def test_the_poller_pauses_the_conversation_when_due(monkeypatch):
    monkeypatch.setattr(slow_tests, "_POLL_SECONDS", 0.01)
    conversation = _Conversation()
    watch = slow_tests.new_watch(600)
    slow_tests.attach(conversation, watch)

    with slow_tests.pause_for_slow_tests(conversation):
        watch.record("npm test", 120)
        for _ in range(200):
            if conversation.paused:
                break
            real_time.sleep(0.01)

    assert conversation.paused


def _paused_conv(runs, sent):
    from openhands.sdk.conversation.state import ConversationExecutionStatus

    class Conv:
        def __init__(self):
            self.state = SimpleNamespace(execution_status=ConversationExecutionStatus.PAUSED)

        def run(self):
            runs["n"] += 1
            if runs["n"] == 2:
                self.state.execution_status = ConversationExecutionStatus.FINISHED

        def send_message(self, text):
            sent.append(text)

        def pause(self):
            pass

    return Conv()


def test_runner_sends_the_note_and_goes_on(monkeypatch):
    from certo import runner

    sent: list[str] = []
    runs = {"n": 0}
    conversation = _paused_conv(runs, sent)
    watch = slow_tests.new_watch(1800)
    slow_tests.attach(conversation, watch)
    watch.record("npm test", 600)
    monkeypatch.setattr(runner, "_remind_text_tool_call", lambda *a, **k: False)

    runner._run_conversation_once(conversation, runner_cfg(), lambda _m: None, None)

    assert runs["n"] == 2
    assert len(sent) == 1 and sent[0].startswith("Certo: this test run took about 10 minute(s)")


def test_after_the_wrap_up_the_note_is_dropped_and_the_run_goes_on(monkeypatch):
    from certo import runner

    sent: list[str] = []
    runs = {"n": 0}
    conversation = _paused_conv(runs, sent)
    watch = slow_tests.new_watch(1800)
    slow_tests.attach(conversation, watch)
    watch.record("npm test", 600)
    monkeypatch.setattr(runner, "wrap_up_for", lambda c: SimpleNamespace(sent=True))
    monkeypatch.setattr(runner, "_remind_text_tool_call", lambda *a, **k: False)

    runner._run_conversation_once(conversation, runner_cfg(), lambda _m: None, None)

    assert runs["n"] == 2
    assert sent == []


def runner_cfg():
    from certo.config import Config

    return Config(
        model="openai/x",
        api_key="k",
        base_url=None,
        workspace=".",
        max_iterations=5,
        confirm_mode="never",
        execution="local",
    )
