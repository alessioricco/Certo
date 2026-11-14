"""wrap_up.py: the acceptance checks told to the agent, and the wrap-up
message before the time budget ends. No model call."""

from __future__ import annotations

from types import SimpleNamespace

from certo import wrap_up
from certo.acceptance import AcceptanceCheck


def _checks():
    return [
        AcceptanceCheck(kind="file_contains", path="NOTES.md", contains="## Part 2"),
        AcceptanceCheck(kind="file_exists", path="dist/index.html"),
        AcceptanceCheck(kind="file_exists", path="extra.txt", required=False),
    ]


def test_the_brief_lists_each_check_in_plain_words():
    brief = wrap_up.acceptance_brief(_checks())

    assert "When you finish, Certo checks that each of these holds" in brief
    assert '- NOTES.md contains the text "## Part 2"' in brief
    assert "- the file dist/index.html exists" in brief
    assert "- the file extra.txt exists (optional)" in brief


def test_no_checks_no_brief():
    assert wrap_up.acceptance_brief(None) == ""
    assert wrap_up.acceptance_brief([]) == ""


def test_the_margin_is_15_percent_between_2_and_10_minutes():
    assert wrap_up.margin_seconds(3600) == 540
    assert wrap_up.margin_seconds(300) == 120
    assert wrap_up.margin_seconds(10_000) == 600


class _Conversation:
    def __init__(self):
        self.paused = False

    def pause(self):
        self.paused = True


def test_the_message_names_only_the_required_checks_that_dont_hold(tmp_path, monkeypatch):
    (tmp_path / "NOTES.md").write_text("## Part 1\n")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(wrap_up.time, "monotonic", lambda: 1000.0)
    conversation = _Conversation()

    wrap = wrap_up.register(
        conversation,
        deadline=1000.0 + 3600,
        budget_seconds=3600,
        workspace=str(tmp_path),
        checks=_checks(),
    )
    assert wrap is not None and wrap.at == 1000.0 + 3600 - 540

    wrap.due = True
    message = wrap_up.take_due_message(conversation, now=1000.0 + 3100)

    assert message.startswith("Certo: about 9 minute(s) of the time budget are left.")
    assert '- NOTES.md contains the text "## Part 2"' in message
    assert "dist/index.html" not in message  # it holds
    assert "extra.txt" not in message  # optional
    assert wrap_up.take_due_message(conversation, now=1000.0 + 3200) is None  # once


def test_no_message_before_it_is_due_or_after_the_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(wrap_up.time, "monotonic", lambda: 0.0)
    conversation = _Conversation()
    wrap = wrap_up.register(
        conversation, deadline=3600, budget_seconds=3600, workspace=str(tmp_path), checks=None
    )

    assert wrap_up.take_due_message(conversation, now=100) is None  # not due
    wrap.due = True
    assert wrap_up.take_due_message(conversation, now=3601) is None  # too late


def test_no_wrap_up_without_a_budget_or_with_a_tiny_one(tmp_path):
    conversation = _Conversation()

    assert (
        wrap_up.register(
            conversation,
            deadline=float("inf"),
            budget_seconds=3600,
            workspace=str(tmp_path),
            checks=None,
        )
        is None
    )
    assert (
        wrap_up.register(
            conversation, deadline=60, budget_seconds=60, workspace=str(tmp_path), checks=None
        )
        is None
    )


def test_the_watcher_pauses_the_conversation_when_due(tmp_path, monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(wrap_up.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(wrap_up, "_POLL_SECONDS", 0.01)
    conversation = _Conversation()
    wrap_up.register(
        conversation, deadline=3600, budget_seconds=3600, workspace=str(tmp_path), checks=None
    )

    import time as real_time

    with wrap_up.pause_for_wrap_up(conversation):
        clock["now"] = 3100.0
        for _ in range(200):
            if conversation.paused:
                break
            real_time.sleep(0.01)

    assert conversation.paused
    assert wrap_up.wrap_up_for(conversation).due


def test_runner_sends_the_wrap_up_and_goes_on(monkeypatch):
    """_run_conversation_once: a run paused for the wrap-up gets the message
    and runs again."""
    from openhands.sdk.conversation.state import ConversationExecutionStatus

    from certo import runner

    sent: list[str] = []
    notices: list = []
    runs = {"n": 0}

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

    conversation = Conv()
    monkeypatch.setattr(
        runner, "take_due_message", lambda c, now=None: "WRAP UP" if runs["n"] == 1 else None
    )
    monkeypatch.setattr(runner, "_remind_text_tool_call", lambda *a, **k: False)

    runner._run_conversation_once(conversation, runner_cfg(), notices.append, None)

    assert runs["n"] == 2
    assert sent == ["WRAP UP"]


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
