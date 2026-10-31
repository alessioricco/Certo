"""End-to-end smoke test for the runner, plus unit tests for the harness-side
verification loop (`_verify_and_report`) — those need no LLM/network, only a
fake `Conversation`-like object and a monkeypatched `_run_verification`.

The e2e test skips cleanly when no LLM key is configured, so CI passes
without secrets. When a key is present, it runs one tiny, cheap task against
whichever provider/model `.env` currently points at (proving the harness is
provider-agnostic: this test never hardcodes a model).
"""

from __future__ import annotations

import errno
import json
import logging
import os
from contextlib import nullcontext
from types import SimpleNamespace
from typing import ClassVar

import pytest
from openhands.sdk import ConversationExecutionStatus
from openhands.sdk.event import ObservationEvent
from openhands.tools.task_tracker import TaskTrackerObservation, TaskTrackerTool

from certo import runner
from certo.acceptance import AcceptanceCheck
from certo.config import Config, ConfigError, load_config
from certo.run_summary import RunSummary
from certo.verification import CheckOutcome, VerificationRun

_REAL_AGENT_CHANGED_FILES = runner._agent_changed_files


@pytest.fixture(autouse=True)
def _agent_changes_a_file(monkeypatch):
    """The fake conversations here never touch the folder. Count every run
    as changing a file, so they keep testing what they test; the tests of
    `unchanged` put the real check back."""
    monkeypatch.setattr(runner, "_agent_changed_files", lambda *_a: True)


def _config_available() -> bool:
    try:
        load_config()
    except ConfigError:
        return False
    return True


@pytest.mark.skipif(
    not _config_available(), reason="No CERTO_LLM_MODEL/CERTO_LLM_API_KEY configured in .env"
)
def test_run_task_creates_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CERTO_WORKSPACE", str(tmp_path))

    from certo.runner import run_task

    target = tmp_path / "HELLO.txt"
    messages = run_task(
        f"Create a file at the absolute path {target} containing the single "
        "line: hello. Then finish."
    )

    assert messages, "expected at least one captured message"
    assert target.exists()
    assert "hello" in target.read_text().lower()
    assert messages.outcome.verification_state in runner.VERIFICATION_STATES


@pytest.mark.skipif(
    not _config_available(), reason="No CERTO_LLM_MODEL/CERTO_LLM_API_KEY configured in .env"
)
def test_run_task_catches_entrypoint_ordering_bug_live(tmp_path, monkeypatch):
    """Closes the "not yet re-verified live" caveat that recurs across
    ARCHITECTURE.md's known limitations for the `entrypoint-ordering`/smoke-run
    checks (todo.md #16): those were previously only unit-tested against a
    synthetic fixture and verified against one frozen historical repro
    (`projects/hanoi/`), never through an actual `run_task()` call driving a
    real LLM end to end.

    Builds its own throwaway fixture in `tmp_path` rather than depending on
    or referencing anything under the repo's own `projects/` directory —
    that's user-managed runtime state, not a harness test fixture.
    """
    monkeypatch.setenv("CERTO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CERTO_VERIFY_TESTS", "always")

    from certo.runner import run_task

    # Same bug shape as test_run_tests_tool.py's
    # test_full_verification_catches_the_live_ordering_bug_even_though_pytest_passes:
    # `helper()` is called from inside the `__main__` guard but defined
    # after it. Invisible to a test suite that only imports the module
    # (pytest passes cleanly); real the moment the script is actually run.
    (tmp_path / "app.py").write_text(
        "def main():\n"
        "    print('start')\n"
        "    helper()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
        "\n"
        "def helper():\n"
        "    print('should have run')\n"
    )
    (tmp_path / "test_app.py").write_text(
        "from app import main\n\ndef test_main_is_importable():\n    assert callable(main)\n"
    )

    messages = run_task(
        "This directory already contains app.py and test_app.py, unrelated "
        "to this task. Do not read, inspect, run, or modify them in any "
        "way. Your only job: create a new file called STATUS.txt in this "
        "same directory containing exactly one line: done. Do not run any "
        "test or verification commands yourself. Then finish."
    )
    outcome = messages.outcome

    assert (tmp_path / "STATUS.txt").exists()
    # Plain pytest alone would have called this project "verified" —
    # confirms the fixture actually reproduces the scenario, not a vacuous
    # check.
    pytest_check = next(c for c in outcome.checks if c.name == "pytest")
    assert pytest_check.status == "passed"
    # The decisive signal: the harness's own live, post-hoc verification
    # loop must have caught a real problem pytest missed and driven at
    # least one automated fix-and-recheck cycle on this live run — it must
    # never silently report "verified" on the first, still-buggy pass.
    assert outcome.retries_used >= 1
    assert outcome.verification_state != "inconclusive"
    ordering_check = next((c for c in outcome.checks if c.name == "entrypoint-ordering"), None)
    if ordering_check is not None:
        assert ordering_check.command == ""  # precomputed static check, no subprocess


def _cfg(**overrides) -> Config:
    base = {
        "model": "openai/gpt-4o",
        "api_key": "key",
        "base_url": None,
        "workspace": ".",
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


def _check(
    name: str = "pytest",
    command: str = "pytest -q",
    *,
    primary: bool = True,
    status: str = "passed",
    exit_code: int | None = 0,
    summary: str = "",
    output: str = "",
) -> CheckOutcome:
    return CheckOutcome(
        name=name,
        command=command,
        primary=primary,
        status=status,
        exit_code=exit_code,
        project_root="/tmp/x",
        summary=summary,
        output=output,
    )


def _run(*checks: CheckOutcome) -> VerificationRun:
    return VerificationRun(checks=list(checks))


class _FakeConversation:
    """Records send_message/run calls instead of driving a real LLM loop.

    `initial_status` is the execution_status `_verify_and_report` sees before
    doing anything (i.e. the result of the harness's own already-completed
    first `conversation.run()`). `statuses_after_run`, if given, is consumed
    one value per subsequent `.run()` call (a retry) to simulate the SDK
    transitioning into a stuck/error state mid-retry; once exhausted, status
    stays whatever it last was — a healthy retry that doesn't get stuck.

    `initial_events`/`events_after_run` do the same for
    `state.events` (consulted by `_enforce_task_tracker_completion`, not by
    `_verify_and_report`) — `events_after_run` values are appended, one per
    `.run()` call, standing in for a task_tracker observation the agent
    produced during that retry.
    """

    def __init__(
        self,
        initial_status: ConversationExecutionStatus = ConversationExecutionStatus.FINISHED,
        statuses_after_run: list[ConversationExecutionStatus] | None = None,
        initial_events: list | None = None,
        events_after_run: list | None = None,
    ) -> None:
        self.sent_messages: list[str] = []
        self.run_calls = 0
        self.state = SimpleNamespace(
            execution_status=initial_status, events=list(initial_events or [])
        )
        self._statuses_after_run = list(statuses_after_run or [])
        self._events_after_run = list(events_after_run or [])

    def send_message(self, message: str) -> None:
        self.sent_messages.append(message)

    def run(self) -> None:
        self.run_calls += 1
        if self._statuses_after_run:
            self.state.execution_status = self._statuses_after_run.pop(0)
        if self._events_after_run:
            self.state.events.append(self._events_after_run.pop(0))


def _task_list_event(*items: dict) -> ObservationEvent:
    """A real `ObservationEvent` wrapping a real `TaskTrackerObservation` —
    constructed for real (not a bare mock) so `isinstance(event,
    ObservationEvent)` checks in `_task_tracker_snapshot` exercise the same
    type check production code relies on.
    """
    observation = TaskTrackerObservation.from_text(
        text="task list", command="plan", task_list=list(items)
    )
    return ObservationEvent(
        tool_name=TaskTrackerTool.name,
        tool_call_id="call_1",
        observation=observation,
        action_id="act_1",
    )


class _ConfirmConversation:
    """Stands in for `Conversation` in `_run_with_confirmation` tests.

    `statuses` is consumed one value per `.run()` call — the status that
    call leaves the conversation in. `_pending_actions` is monkeypatched
    separately in these tests rather than reconstructed from real events,
    since the SDK's own action/observation matching logic isn't what's
    under test here — only `_run_with_confirmation`'s approve/reject/
    no-handler control flow is.
    """

    def __init__(self, statuses: list[ConversationExecutionStatus]) -> None:
        # Unlike _FakeConversation, _run_with_confirmation always calls
        # .run() unconditionally as its first action (there's no
        # already-completed prior run to reflect), so every status in the
        # list is consumed by a .run() call — none are "pre-run" state.
        self._statuses = list(statuses)
        self.state = SimpleNamespace(execution_status=None)
        self.run_calls = 0
        self.rejected_reasons: list[str] = []
        self.confirmation_policies: list[object] = []

    def send_message(self, message: str) -> None:
        pass

    def run(self) -> None:
        self.run_calls += 1
        self.state.execution_status = self._statuses.pop(0)

    def reject_pending_actions(self, reason: str) -> None:
        self.rejected_reasons.append(reason)

    def set_confirmation_policy(self, policy: object) -> None:
        self.confirmation_policies.append(policy)


_FAKE_PENDING = [SimpleNamespace(tool_name="terminal", action="echo hi")]


# --- CERTO_CONFIRM_MODE=always wiring (_run_with_confirmation) -----------


def test_run_with_confirmation_is_a_noop_when_confirm_mode_is_never():
    conversation = _ConfirmConversation([ConversationExecutionStatus.FINISHED])

    result = runner._run_with_confirmation(
        conversation, _cfg(confirm_mode="never"), lambda _m: None, on_confirm=None
    )

    assert result == "ok"
    assert conversation.run_calls == 1
    assert conversation.rejected_reasons == []


def test_run_with_confirmation_approves_and_continues(monkeypatch):
    monkeypatch.setattr(runner, "_pending_actions", lambda _conv: _FAKE_PENDING)
    conversation = _ConfirmConversation(
        [
            ConversationExecutionStatus.WAITING_FOR_CONFIRMATION,
            ConversationExecutionStatus.FINISHED,
        ]
    )
    seen = []

    def _approve(pending):
        seen.append(list(pending))
        return True

    result = runner._run_with_confirmation(
        conversation, _cfg(confirm_mode="always"), lambda _m: None, on_confirm=_approve
    )

    assert result == "ok"
    assert conversation.run_calls == 2
    assert seen == [_FAKE_PENDING]
    assert conversation.rejected_reasons == []


def test_run_with_confirmation_rejects_then_continues(monkeypatch):
    monkeypatch.setattr(runner, "_pending_actions", lambda _conv: _FAKE_PENDING)
    conversation = _ConfirmConversation(
        [
            ConversationExecutionStatus.WAITING_FOR_CONFIRMATION,
            ConversationExecutionStatus.FINISHED,
        ]
    )

    result = runner._run_with_confirmation(
        conversation, _cfg(confirm_mode="always"), lambda _m: None, on_confirm=lambda _p: False
    )

    assert result == "ok"
    assert conversation.run_calls == 2
    assert conversation.rejected_reasons == ["Rejected by the user via Certo confirm-mode."]


def test_run_with_confirmation_stops_and_rejects_once_when_no_handler(monkeypatch):
    # No on_confirm callback available (e.g. server mode) — must not
    # silently approve (defeats the safety gate) or loop forever with
    # nobody able to answer.
    monkeypatch.setattr(runner, "_pending_actions", lambda _conv: _FAKE_PENDING)
    conversation = _ConfirmConversation([ConversationExecutionStatus.WAITING_FOR_CONFIRMATION])
    emitted = []

    result = runner._run_with_confirmation(
        conversation, _cfg(confirm_mode="always"), emitted.append, on_confirm=None
    )

    assert result == "confirmation_required"
    assert conversation.run_calls == 1  # no further run() calls after the unanswered pause
    assert len(conversation.rejected_reasons) == 1
    assert len(emitted) == 1
    assert "no interactive approval" in emitted[0].content[0].text


def test_stream_task_sets_always_confirm_policy_when_confirm_mode_always(monkeypatch):
    conversation = _ConfirmConversation([ConversationExecutionStatus.FINISHED])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state="inconclusive",
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )

    runner.stream_task("do the thing", cfg=_cfg(confirm_mode="always"))

    assert len(conversation.confirmation_policies) == 1
    from openhands.sdk.security.confirmation_policy import AlwaysConfirm

    assert isinstance(conversation.confirmation_policies[0], AlwaysConfirm)


def test_stream_task_short_circuits_when_confirmation_required_with_no_handler(monkeypatch):
    monkeypatch.setattr(runner, "_pending_actions", lambda _conv: _FAKE_PENDING)
    conversation = _ConfirmConversation([ConversationExecutionStatus.WAITING_FOR_CONFIRMATION])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    tracker_calls = {"count": 0}
    monkeypatch.setattr(
        runner,
        "_enforce_task_tracker_completion",
        lambda *a, **kw: tracker_calls.__setitem__("count", tracker_calls["count"] + 1),
    )

    outcome = runner.stream_task("do the thing", cfg=_cfg(confirm_mode="always"))

    assert outcome.verification_state == "confirmation_required"
    assert tracker_calls["count"] == 0  # never reached task_tracker enforcement


# --- CERTO_INTERACTIVE=yes: initial-run interactive checkpoint -----------


class _ManualClock:
    """A fake `time.monotonic` that only advances when explicitly told to —
    avoids needing to predict the exact number of `time.monotonic()` calls a
    code path makes (fragile), unlike a fixed-value iterator.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _mock_task_tracker_and_verify(monkeypatch, verification_state: str = "verified") -> None:
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state=verification_state,
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )


def test_interactive_loop_sends_reply_and_reruns_until_enter(monkeypatch):
    conversation = _FakeConversation(
        statuses_after_run=[
            ConversationExecutionStatus.FINISHED,  # initial run
            ConversationExecutionStatus.FINISHED,  # after the human's reply
        ]
    )
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    _mock_task_tracker_and_verify(monkeypatch, verification_state="inconclusive")
    replies = iter(["please also add tests", None])
    prompted = []

    def on_awaiting_input(narrative: str) -> str | None:
        prompted.append(narrative)
        return next(replies)

    outcome = runner.stream_task(
        "do the thing", cfg=_cfg(interactive=True), on_awaiting_input=on_awaiting_input
    )

    assert conversation.run_calls == 2
    assert conversation.sent_messages == ["do the thing", "please also add tests"]
    assert len(prompted) == 2
    assert outcome.verification_state == "inconclusive"


def test_interactive_loop_ends_immediately_on_enter_and_proceeds_normally(monkeypatch):
    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.FINISHED])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    tracker_calls = {"count": 0}

    def _count_tracker(*_a, **_kw):
        tracker_calls["count"] += 1

    _mock_task_tracker_and_verify(monkeypatch)
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", _count_tracker)
    prompted = []

    def on_awaiting_input(narrative: str) -> str | None:
        prompted.append(narrative)
        return None

    runner.stream_task(
        "do the thing", cfg=_cfg(interactive=True), on_awaiting_input=on_awaiting_input
    )

    assert conversation.run_calls == 1
    assert len(prompted) == 1
    assert tracker_calls["count"] == 1  # proceeded to the normal autonomous flow afterward


def test_interactive_without_a_callback_never_loops(monkeypatch):
    # CERTO_INTERACTIVE=yes with no on_awaiting_input (e.g. server.py,
    # which never supplies one) must behave like a single ordinary run —
    # regression guard for the documented server-mode gotcha.
    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.FINISHED])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    _mock_task_tracker_and_verify(monkeypatch, verification_state="inconclusive")

    runner.stream_task("do the thing", cfg=_cfg(interactive=True), on_awaiting_input=None)

    assert conversation.run_calls == 1


def test_interactive_false_ignores_a_supplied_callback(monkeypatch):
    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.FINISHED])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    _mock_task_tracker_and_verify(monkeypatch, verification_state="inconclusive")

    def _fail_if_called(_narrative: str) -> str | None:
        raise AssertionError("on_awaiting_input must not be called when cfg.interactive is False")

    runner.stream_task(
        "do the thing", cfg=_cfg(interactive=False), on_awaiting_input=_fail_if_called
    )

    assert conversation.run_calls == 1


def test_interactive_loop_does_not_trigger_on_a_stuck_status(monkeypatch):
    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.STUCK])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))

    def _fail_if_called(_narrative: str) -> str | None:
        raise AssertionError("on_awaiting_input must not be called on a stuck/error status")

    outcome = runner.stream_task(
        "do the thing", cfg=_cfg(interactive=True), on_awaiting_input=_fail_if_called
    )

    assert outcome.verification_state == "stuck"
    assert conversation.run_calls == 1


def test_interactive_wait_time_is_excluded_from_the_task_budget(monkeypatch):
    # A human can take arbitrarily long to reply without the shared
    # CERTO_MAX_TASK_SECONDS budget being spent on that wait — only actual
    # agent run time should count. Proven by simulating a "wait" many times
    # longer than the whole configured budget and confirming the task still
    # completes normally instead of reporting budget_exhausted.
    conversation = _FakeConversation(
        statuses_after_run=[
            ConversationExecutionStatus.FINISHED,
            ConversationExecutionStatus.FINISHED,
        ]
    )
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    _mock_task_tracker_and_verify(monkeypatch, verification_state="verified")
    clock = _ManualClock()
    monkeypatch.setattr(runner.time, "monotonic", clock)
    replies = iter(["keep going", None])

    def on_awaiting_input(_narrative: str) -> str | None:
        clock.advance(999.0)  # far longer than max_task_seconds below
        return next(replies)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(interactive=True, max_task_seconds=5),
        on_awaiting_input=on_awaiting_input,
    )

    assert conversation.run_calls == 2
    assert outcome.verification_state == "verified"


# --- CERTO_MAX_TASK_SECONDS: shared task-level budget ---------------------
#
# Regression coverage for the gap logged in DECISIONS.md: CERTO_MAX_ITERATIONS
# only bounds a single conversation.run() call, but runner.py can call
# .run() up to three times per task (the initial run, then up to
# max_verify_retries more in each of the two retry loops), each getting its
# own fresh iteration budget from the SDK — so a task could spend roughly
# max_iterations * (1 + 2 * max_verify_retries) iterations, well beyond what
# the configured cap suggests. `deadline` (an absolute time.monotonic()
# timestamp) is checked before every conversation.run() call these tests
# exercise.


def test_run_with_confirmation_reports_budget_exhausted_before_any_run_call():
    conversation = _ConfirmConversation([ConversationExecutionStatus.FINISHED])

    result = runner._run_with_confirmation(
        conversation, _cfg(confirm_mode="never"), lambda _m: None, on_confirm=None, deadline=-1.0
    )

    assert result == "budget_exhausted"
    assert conversation.run_calls == 0  # never even attempted the run


def test_run_with_confirmation_reports_budget_exhausted_mid_confirm_loop(monkeypatch):
    # The deadline passes *between* two confirm-mode round-trips, not before
    # the very first .run() call — must still be caught, not just checked
    # once at the top. First time.monotonic() call is the pre-run check
    # (still within budget); the second is inside the confirm loop, after
    # the initial run already paused for confirmation (budget now exhausted).
    monkeypatch.setattr(runner, "_pending_actions", lambda _conv: _FAKE_PENDING)
    conversation = _ConfirmConversation([ConversationExecutionStatus.WAITING_FOR_CONFIRMATION])
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    # The deadline guard reads the clock too (tested in test_deadline.py).
    monkeypatch.setattr(runner, "stop_at_deadline", lambda *_a: nullcontext())

    result = runner._run_with_confirmation(
        conversation,
        _cfg(confirm_mode="always"),
        lambda _m: None,
        on_confirm=lambda _p: True,
        deadline=5.0,
    )

    assert result == "budget_exhausted"
    assert conversation.run_calls == 1  # the initial run only — no approved retry


def test_verify_and_report_checks_the_work_when_the_budget_ran_out_and_it_passes(monkeypatch):
    # The budget is checked only between runs, so the last run can end after
    # it. The checks need no model: passing work is verified, with a note,
    # and no fix attempt is made.
    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(summary="3 passed"))
    )
    conversation = _FakeConversation()
    notices: list = []

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), notices.append, "do the thing", deadline=-1.0
    )

    assert outcome.verification_state == "verified"
    assert len(outcome.checks) == 1
    assert any(
        "ran out before the agent finished" in n for n in outcome.completion_contract.limitations
    )
    assert any("time budget" in str(n) for n in notices)
    assert conversation.run_calls == 0


def test_verify_and_report_keeps_budget_exhausted_with_the_checks_when_they_fail(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(status="failed", exit_code=1, summary="1 failed")),
    )
    conversation = _FakeConversation()

    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5),
        lambda _m: None,
        "do the thing",
        deadline=-1.0,
    )

    assert outcome.verification_state == "budget_exhausted"
    assert [c.status for c in outcome.checks] == ["failed"]
    assert outcome.retries_used == 0
    assert conversation.run_calls == 0  # no time left for a fix attempt


@pytest.mark.parametrize(
    ("status", "verify_tests"),
    [
        (ConversationExecutionStatus.ERROR, "always"),
        (ConversationExecutionStatus.FINISHED, "never"),
    ],
)
def test_verify_and_report_skips_the_checks_after_the_budget_for_an_error_or_checks_off(
    monkeypatch, status, verify_tests
):
    def _must_not_verify(*_a):
        raise AssertionError("checks must not run")

    monkeypatch.setattr(runner, "_run_verification", _must_not_verify)
    conversation = _FakeConversation(initial_status=status)

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests=verify_tests), lambda _m: None, "do", deadline=-1.0
    )

    assert outcome.verification_state == "budget_exhausted"
    assert outcome.checks == ()


def test_a_model_call_cut_at_the_deadline_ends_the_run_and_its_work_is_checked(monkeypatch):
    from openhands.sdk.conversation.exceptions import ConversationRunError
    from openhands.sdk.llm.exceptions.types import LLMTimeoutError

    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(summary="3 passed"))
    )
    conversation = _SwitchableConversation(
        [ConversationRunError("c", LLMTimeoutError("timed out"))],
        initial_status=ConversationExecutionStatus.ERROR,
    )
    conversation.pause = lambda: None  # deadline.py pauses it at once

    runner._run_conversation_once(conversation, _cfg(), lambda _m: None, None, deadline=-1.0)
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), lambda _m: None, "do", deadline=-1.0
    )

    assert outcome.verification_state == "verified"  # checked, not stuck or unchecked


def test_a_model_error_before_the_deadline_still_raises():
    from openhands.sdk.conversation.exceptions import ConversationRunError
    from openhands.sdk.llm.exceptions.types import LLMTimeoutError

    conversation = _SwitchableConversation(
        [ConversationRunError("c", LLMTimeoutError("timed out"))]
    )

    with pytest.raises(ConversationRunError):
        runner._run_conversation_once(conversation, _cfg(), lambda _m: None, None)
    assert conversation not in runner._CUT_AT_DEADLINE


def _agent_says(text: str):
    from openhands.sdk import Message, TextContent
    from openhands.sdk.event import MessageEvent

    return MessageEvent(
        source="agent", llm_message=Message(role="assistant", content=[TextContent(text=text)])
    )


_TEXT_CALL = '{"command": "view", "path": "/tmp/project"}'


def _notice_texts(notices: list) -> list[str]:
    return ["".join(c.text for c in m.content) for m in notices]


def test_a_run_that_ends_on_a_tool_call_written_as_text_is_sent_back_once():
    # The model's first answer is a tool call as text; after the reminder
    # it works and ends with prose.
    conversation = _FakeConversation(
        events_after_run=[_agent_says(_TEXT_CALL), _agent_says("Done, all tests pass.")]
    )
    notices: list = []

    runner._run_conversation_once(conversation, _cfg(), notices.append, None)

    assert conversation.run_calls == 2
    assert conversation.sent_messages == [runner.TOOL_CALL_REMINDER]
    assert any("tool call as text" in n and "(1 of 3)" in n for n in _notice_texts(notices))


def test_tool_call_reminders_stop_at_the_limit():
    conversation = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL) for _ in range(5)])

    runner._run_conversation_once(conversation, _cfg(tool_call_reminders=2), lambda _m: None, None)

    assert conversation.run_calls == 3
    assert len(conversation.sent_messages) == 2


def test_tool_call_reminders_0_turns_them_off():
    conversation = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL)])

    runner._run_conversation_once(conversation, _cfg(tool_call_reminders=0), lambda _m: None, None)

    assert conversation.run_calls == 1
    assert conversation.sent_messages == []


def test_reminders_sent_counts_them_for_the_benchmark():
    conversation = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL) for _ in range(5)])
    assert runner._reminders_sent(conversation) == 0

    runner._run_conversation_once(conversation, _cfg(tool_call_reminders=2), lambda _m: None, None)

    assert runner._reminders_sent(conversation) == 2
    # A conversation never reminded (a model that makes real tool calls) reads 0.
    assert runner._reminders_sent(_FakeConversation()) == 0


def test_the_same_text_call_is_not_reminded_twice():
    # After the reminder the run adds nothing: the last agent message is
    # still the one already reminded about.
    conversation = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL)])

    runner._run_conversation_once(conversation, _cfg(), lambda _m: None, None)

    assert conversation.run_calls == 2
    assert len(conversation.sent_messages) == 1


@pytest.mark.parametrize(
    "status", [ConversationExecutionStatus.STUCK, ConversationExecutionStatus.PAUSED]
)
def test_no_reminder_unless_the_run_finished(status):
    conversation = _FakeConversation(
        statuses_after_run=[status], events_after_run=[_agent_says(_TEXT_CALL)]
    )

    runner._run_conversation_once(conversation, _cfg(), lambda _m: None, None)

    assert conversation.sent_messages == []


def test_no_reminder_for_a_prose_answer_or_after_the_deadline():
    prose = _FakeConversation(events_after_run=[_agent_says("All done.")])
    runner._run_conversation_once(prose, _cfg(), lambda _m: None, None)
    assert prose.sent_messages == []

    late = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL)])
    late.pause = lambda: None  # deadline.py pauses it at once
    runner._run_conversation_once(late, _cfg(), lambda _m: None, None, deadline=-1.0)
    assert late.sent_messages == []


def test_the_reminder_uses_the_agents_own_tools():
    # A call to a tool this agent doesn't have is not a call.
    tool = SimpleNamespace(action_type=SimpleNamespace(model_fields={"query": None}))
    conversation = _FakeConversation(events_after_run=[_agent_says(_TEXT_CALL)])
    conversation.agent = SimpleNamespace(tools_map={"search": tool})

    runner._run_conversation_once(conversation, _cfg(), lambda _m: None, None)

    assert conversation.sent_messages == []


def test_verify_and_report_reports_budget_exhausted_mid_retry(monkeypatch):
    # deadline is still valid at entry (the first time.monotonic() call
    # returns a value below it) but exhausted by the time the retry loop's
    # own _run_with_confirmation call checks again (the second call).
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(status="failed", exit_code=1, summary="1 failed")),
    )
    conversation = _FakeConversation()
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))

    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5),
        lambda _m: None,
        "do the thing",
        on_confirm=None,
        deadline=50.0,
    )

    assert outcome.verification_state == "budget_exhausted"
    assert outcome.retries_used == 1
    assert conversation.run_calls == 0


def test_enforce_task_tracker_completion_reports_budget_exhausted_at_entry():
    conversation = _FakeConversation(
        initial_events=[_task_list_event({"title": "B", "status": "todo"})]
    )

    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), lambda _m: None, "do the thing", deadline=-1.0
    )

    assert outcome is not None
    assert outcome.verification_state == "budget_exhausted"
    assert conversation.run_calls == 0


@pytest.mark.parametrize(
    "events", [[], [_task_list_event({"title": "B", "status": "done"})]], ids=["no-list", "done"]
)
def test_enforce_task_tracker_completion_leaves_a_late_finish_to_the_checks(events):
    # Budget gone, but nothing left on the list: the project's checks decide.
    conversation = _FakeConversation(initial_events=events)

    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), lambda _m: None, "do the thing", deadline=-1.0
    )

    assert outcome is None
    assert conversation.run_calls == 0


def test_enforce_task_tracker_completion_reports_budget_exhausted_mid_retry(monkeypatch):
    # Same shape as _verify_and_report's equivalent test: deadline is still
    # valid at entry, exhausted by the time the retry loop's own
    # _run_with_confirmation call checks again.
    conversation = _FakeConversation(
        initial_events=[_task_list_event({"title": "B", "status": "todo"})]
    )
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))

    outcome = runner._enforce_task_tracker_completion(
        conversation,
        _cfg(max_verify_retries=5),
        lambda _m: None,
        "do the thing",
        on_confirm=None,
        deadline=50.0,
    )

    assert outcome is not None
    assert outcome.verification_state == "budget_exhausted"
    assert outcome.retries_used == 1
    assert conversation.run_calls == 0


# --- CERTO_MAX_TASK_COST (cost_limit.py) ------------------------------------


class _SpendingConversation(_FakeConversation):
    """A _FakeConversation whose model costs `per_run` USD each `.run()`."""

    def __init__(self, *, per_run: float = 0.0, spent: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.metrics = SimpleNamespace(accumulated_cost=spent)
        self.conversation_stats = SimpleNamespace(usage_to_metrics={"certo": self.metrics})
        self.per_run = per_run
        self.paused = False

    def run(self) -> None:
        super().run()
        self.metrics.accumulated_cost += self.per_run

    def pause(self) -> None:
        self.paused = True


def _over_the_limit(**kwargs) -> _SpendingConversation:
    conversation = _SpendingConversation(**kwargs)
    runner.set_cost_limit(conversation, 1.0, spent_before=1.0)
    return conversation


def test_no_run_starts_once_the_cost_limit_is_reached():
    conversation = _over_the_limit()

    result = runner._run_with_confirmation(
        conversation, _cfg(max_task_cost=1.0), lambda _m: None, on_confirm=None
    )

    assert result == "cost_exhausted"
    assert conversation.run_calls == 0


def test_a_run_that_reaches_the_cost_limit_says_so_once():
    conversation = _SpendingConversation(per_run=0.6)
    runner.set_cost_limit(conversation, 1.0)
    cfg = _cfg(max_task_cost=1.0)
    notices: list = []

    for _ in range(3):
        runner._run_conversation_once(conversation, cfg, notices.append, None)

    texts = [str(n) for n in notices]
    assert len(texts) == 1
    assert "has cost $1.2000, reaching its limit (CERTO_MAX_TASK_COST=1)" in texts[0]


def test_work_that_passes_after_the_cost_limit_is_verified(monkeypatch):
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: _run(_check()))
    conversation = _over_the_limit()
    notices: list = []

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always", max_task_cost=1.0), notices.append, "task"
    )

    assert outcome.verification_state == "verified"
    assert any("cost limit was reached" in str(n) for n in notices)
    assert any(
        "The cost limit was reached before the agent finished" in n
        for n in outcome.completion_contract.limitations
    )
    assert conversation.run_calls == 0


def test_failing_work_after_the_cost_limit_is_cost_exhausted_with_no_fix_attempt(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(status="failed", exit_code=1, summary="1 failed")),
    )
    conversation = _over_the_limit()

    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5, max_task_cost=1.0),
        lambda _m: None,
        "task",
    )

    assert outcome.verification_state == "cost_exhausted"
    assert [c.status for c in outcome.checks] == ["failed"]
    assert "CERTO_MAX_TASK_COST=1" in outcome.completion_contract.limitations[0]
    assert conversation.run_calls == 0


def test_a_fix_attempt_past_the_cost_limit_is_not_started(monkeypatch):
    failures = iter(range(10))
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(
            _check(status="failed", exit_code=1, output=f"failure {next(failures)}")
        ),
    )
    # Under the limit when the checks run; the first fix attempt then
    # reaches it, so a second one never starts.
    conversation = _SpendingConversation(per_run=1.0)
    runner.set_cost_limit(conversation, 1.0)

    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5, max_task_cost=1.0),
        lambda _m: None,
        "task",
    )

    assert outcome.verification_state == "cost_exhausted"
    assert conversation.run_calls == 1


def test_open_task_items_after_the_cost_limit_are_cost_exhausted():
    conversation = _over_the_limit(
        initial_events=[_task_list_event({"title": "B", "status": "todo"})]
    )

    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_task_cost=1.0), lambda _m: None, "task"
    )

    assert outcome is not None and outcome.verification_state == "cost_exhausted"
    assert conversation.run_calls == 0


def test_stream_task_gives_the_conversation_the_cost_limit(monkeypatch, tmp_path):
    captured: dict = {}
    _stub_for_env_tests(monkeypatch, captured)
    limits: list = []
    monkeypatch.setattr(runner, "set_cost_limit", lambda conv, *a: limits.append(a))

    runner.stream_task("do the thing", cfg=_cfg(workspace=str(tmp_path), max_task_cost=2.5))

    assert limits == [(2.5, 0.0)]


def test_the_independent_tests_cost_counts_toward_the_limit():
    written = SimpleNamespace(
        metrics={"a": {"accumulated_cost": 0.25}, "b": {"accumulated_cost": None}}
    )

    assert runner._metrics_cost(written) == 0.25
    assert runner._metrics_cost(None) == 0.0


def test_stream_task_short_circuits_when_task_budget_already_exhausted(monkeypatch):
    # time.monotonic() calls, in order: stream_task's run-summary start time;
    # `deadline = now + max_task_seconds`; _run_with_confirmation's own
    # check, simulating that max_task_seconds' worth of wall-clock time has
    # already passed (a tiny max_task_seconds makes this realistic, but the
    # clock is mocked so the test doesn't need to actually wait); and the
    # run summary's end time.
    conversation = _RecordingConversation()
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    tracker_calls = {"count": 0}
    monkeypatch.setattr(
        runner,
        "_enforce_task_tracker_completion",
        lambda *a, **kw: tracker_calls.__setitem__("count", tracker_calls["count"] + 1),
    )
    clock = iter([0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))

    outcome = runner.stream_task("do the thing", cfg=_cfg(max_task_seconds=1, verify_tests="never"))

    assert outcome.verification_state == "budget_exhausted"
    assert outcome.run_summary.duration_seconds == 100.0
    assert tracker_calls["count"] == 0  # never reached task_tracker enforcement


# --- verify_tests=never: verification is skipped entirely ------------------


def test_verify_tests_never_mode_skips_entirely(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: calls.__setitem__("count", calls["count"] + 1) or _run(),
    )

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="never"), emitted.append, "do the thing"
    )

    assert calls["count"] == 0
    assert conversation.run_calls == 0
    assert emitted == []
    assert outcome.verification_state == "inconclusive"
    assert any("skipped" in note for note in outcome.completion_contract.limitations)


# --- successful verification ------------------------------------------------


def test_verify_tests_passes_on_first_check_reports_verified(monkeypatch):
    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(summary="3 passed"))
    )

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 0
    assert conversation.sent_messages == []
    assert emitted == []
    assert outcome.verification_state == "verified"
    assert outcome.success is True
    assert outcome.retries_used == 0
    assert "pytest -q" in outcome.completion_contract.verification_checks


# --- inconclusive verification ----------------------------------------------


def test_no_tests_collected_is_inconclusive_not_verified_and_stays_silent(monkeypatch):
    # The one exemption req'd to keep pre-existing behavior (see MANUAL.md
    # "Test verification"): pytest ran cleanly and found zero tests. Not a
    # failure, but also not proof the software works — must report
    # "inconclusive", not "verified", while keeping the original quiet,
    # non-blocking behavior for this specific, well-defined signal.
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(status="skipped", exit_code=5, summary="no tests ran")),
    )

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 0
    assert emitted == []
    assert outcome.verification_state == "inconclusive"
    assert outcome.success is False


def test_no_runnable_check_is_inconclusive_and_visibly_flagged(monkeypatch):
    # Unlike the clean "no tests collected" case above, a verification pass
    # that produced no checks at all (e.g. run_full_verification raised and
    # _run_verification swallowed it) is a genuine "we don't know" and must
    # be visible, not silently treated as fine.
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: _run())

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 0
    assert len(emitted) == 1
    assert "not independently verified" in emitted[0].content[0].text
    assert outcome.verification_state == "inconclusive"


def test_run_verification_swallows_a_verification_glitch(monkeypatch):
    # A hung/erroring check must not abort an otherwise-successful task.
    def _boom(_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "run_full_verification", _boom)

    result = runner._run_verification("/some/dir")

    assert result.checks == []
    assert result.state == "inconclusive"


# --- failing verification, then a successful retry --------------------------


def test_verify_tests_retries_then_succeeds(monkeypatch):
    results = iter(
        [
            _run(
                _check(
                    status="failed", exit_code=1, summary="1 failed", output="AssertionError: boom"
                )
            ),
            _run(_check(status="passed", summary="3 passed")),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=2),
        emitted.append,
        "do the thing",
    )

    assert conversation.run_calls == 1
    assert len(conversation.sent_messages) == 1
    assert "still failing" in conversation.sent_messages[0]
    assert emitted == []  # recovered — no giving-up notice
    assert outcome.verification_state == "verified"
    assert outcome.retries_used == 1


# --- retry exhaustion --------------------------------------------------------


def test_verify_tests_exhausts_retries_and_emits_giveup_notice(monkeypatch):
    # Each attempt fails differently (a distinct output each time) so this
    # exercises genuine exhaustion, not the separate "no_progress" path
    # (identical failure signature) covered below.
    results = iter(
        [
            _run(
                _check(
                    status="failed", exit_code=1, summary="2 failed", output="AssertionError: one"
                )
            ),
            _run(
                _check(
                    status="failed", exit_code=1, summary="2 failed", output="AssertionError: two"
                )
            ),
            _run(
                _check(
                    status="failed", exit_code=1, summary="2 failed", output="AssertionError: three"
                )
            ),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=2),
        emitted.append,
        "do the thing",
    )

    assert conversation.run_calls == 2
    assert len(conversation.sent_messages) == 2
    assert len(emitted) == 1
    notice_text = emitted[0].content[0].text
    assert "still failing" in notice_text
    assert "2 automated fix attempt" in notice_text
    assert outcome.verification_state == "retry_exhausted"
    assert outcome.retries_used == 2
    assert outcome.success is False


# --- agent stuck / aborted ---------------------------------------------------


def test_stuck_before_verification_skips_checks_entirely(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: calls.__setitem__("count", calls["count"] + 1) or _run(),
    )

    conversation = _FakeConversation(initial_status=ConversationExecutionStatus.STUCK)
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert calls["count"] == 0  # never even tried to verify a stuck run
    assert conversation.run_calls == 0
    assert len(emitted) == 1
    assert "stuck" in emitted[0].content[0].text.lower()
    assert outcome.verification_state == "stuck"
    assert outcome.success is False
    assert any(
        "did not reach a normal finish" in note for note in outcome.completion_contract.limitations
    )


def test_error_status_before_verification_is_also_reported_as_stuck(monkeypatch):
    conversation = _FakeConversation(initial_status=ConversationExecutionStatus.ERROR)
    emitted = []
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert outcome.verification_state == "stuck"
    assert "'error'" in emitted[0].content[0].text


def test_agent_gets_stuck_mid_retry(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(status="failed", exit_code=1, summary="1 failed")),
    )

    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.STUCK])
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=2),
        emitted.append,
        "do the thing",
    )

    assert conversation.run_calls == 1  # got stuck on the first retry, no second attempt
    assert len(emitted) == 1
    assert "stuck" in emitted[0].content[0].text.lower()
    assert outcome.verification_state == "stuck"
    assert outcome.retries_used == 1


def _step_limit_event(code: str = "MaxIterationsReached"):
    from openhands.sdk.event.conversation_error import ConversationErrorEvent

    return ConversationErrorEvent(
        source="environment", code=code, detail="Agent reached maximum iterations limit (10)."
    )


def test_a_step_limit_stop_is_checked_and_can_be_verified(monkeypatch):
    # Live 2026-10-19: the agent's 50th step ran 116 passing tests and the
    # run ended `stuck`. A step-limit stop is now checked like a finish.
    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(status="passed"))
    )
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.ERROR, initial_events=[_step_limit_event()]
    )
    emitted = []

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert outcome.verification_state == "verified"
    assert "used all its 10 steps (CERTO_MAX_ITERATIONS)" in emitted[0].content[0].text


def test_a_step_limit_stop_with_failing_checks_gets_a_fix_attempt(monkeypatch):
    results = iter([_run(_check(status="failed", exit_code=1)), _run(_check(status="passed"))])
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.ERROR,
        initial_events=[_step_limit_event()],
        statuses_after_run=[ConversationExecutionStatus.FINISHED],
    )

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always", max_verify_retries=2), lambda _m: None, "t"
    )

    assert conversation.run_calls == 1  # one fix attempt, with fresh steps
    assert outcome.verification_state == "verified"
    assert outcome.retries_used == 1


def test_a_step_limit_stop_with_nothing_to_check_stays_stuck(monkeypatch):
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: _run())
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.ERROR, initial_events=[_step_limit_event()]
    )
    emitted = []

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), emitted.append, "do the thing"
    )

    assert outcome.verification_state == "stuck"
    assert "used all its steps before finishing" in emitted[-1].content[0].text


def test_another_error_still_ends_stuck_without_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_run_verification", lambda *_a: calls.append(1) or _run())
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.ERROR,
        initial_events=[_step_limit_event(code="SomethingElse")],
    )

    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), lambda _m: None, "do the thing"
    )

    assert outcome.verification_state == "stuck"
    assert calls == []


def test_a_step_limit_stop_skips_the_task_tracker_follow_up():
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.ERROR, initial_events=[_step_limit_event()]
    )

    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(), lambda _m: None, "do the thing"
    )

    assert outcome is None  # verification decides, not `stuck`
    assert conversation.run_calls == 0


# --- task_tracker completion enforcement ------------------------------------
#
# Regression coverage for the "agent declares done with incomplete
# task_tracker items" failure mode logged in DECISIONS.md: prior to this,
# only a prompt-level mitigation (_AUTONOMOUS_SUFFIX) existed, which is soft
# and unverifiable by a test. Live-confirmed the exact failure this guards
# against: given "create two tasks, mark one done, leave the other todo,
# then finish", the agent did exactly that and called finish anyway — see
# DECISIONS.md for the transcript.


def test_task_tracker_never_used_is_not_enforced():
    # The tool's own guidance says trivial tasks don't need it — no
    # task_tracker observation at all must not be treated as a violation.
    conversation = _FakeConversation()
    emitted = []
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), emitted.append, "do the thing"
    )

    assert outcome is None
    assert conversation.run_calls == 0
    assert emitted == []


def test_task_tracker_all_done_is_not_enforced():
    conversation = _FakeConversation(
        initial_events=[_task_list_event({"title": "A", "status": "done"})]
    )
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), lambda _m: None, "do the thing"
    )

    assert outcome is None
    assert conversation.run_calls == 0


def test_task_tracker_pending_item_triggers_followup_then_recovers():
    conversation = _FakeConversation(
        initial_events=[
            _task_list_event({"title": "A", "status": "done"}, {"title": "B", "status": "todo"})
        ],
        events_after_run=[
            _task_list_event({"title": "A", "status": "done"}, {"title": "B", "status": "done"})
        ],
    )
    emitted = []
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 1
    assert len(conversation.sent_messages) == 1
    assert "task_tracker" in conversation.sent_messages[0]
    assert "B" in conversation.sent_messages[0]
    assert emitted == []  # recovered — no give-up notice
    assert outcome is None  # complete now — stream_task proceeds to _verify_and_report


def test_task_tracker_exhausts_retries_and_emits_giveup_notice():
    conversation = _FakeConversation(
        initial_events=[_task_list_event({"title": "B", "status": "todo"})],
        events_after_run=[
            _task_list_event({"title": "B", "status": "in_progress"}),
            _task_list_event({"title": "B", "status": "in_progress"}),
        ],
    )
    emitted = []
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 2
    assert outcome is not None
    assert outcome.verification_state == "incomplete"
    assert outcome.retries_used == 2
    assert outcome.success is False
    assert len(emitted) == 1
    assert "task_tracker" in emitted[0].content[0].text
    assert "B" in emitted[0].content[0].text
    assert any("B" in note for note in outcome.completion_contract.limitations)
    assert outcome.completion_contract.verification_checks == []


def test_task_tracker_stuck_before_check_is_reported_as_stuck():
    conversation = _FakeConversation(
        initial_status=ConversationExecutionStatus.STUCK,
        initial_events=[_task_list_event({"title": "B", "status": "todo"})],
    )
    emitted = []
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 0  # never even tried to follow up on a stuck run
    assert outcome is not None
    assert outcome.verification_state == "stuck"
    assert len(emitted) == 1


def test_task_tracker_gets_stuck_mid_retry():
    conversation = _FakeConversation(
        initial_events=[_task_list_event({"title": "B", "status": "todo"})],
        statuses_after_run=[ConversationExecutionStatus.STUCK],
    )
    emitted = []
    outcome = runner._enforce_task_tracker_completion(
        conversation, _cfg(max_verify_retries=2), emitted.append, "do the thing"
    )

    assert conversation.run_calls == 1  # got stuck on the first retry, no second attempt
    assert outcome is not None
    assert outcome.verification_state == "stuck"
    assert outcome.retries_used == 1


def test_task_tracker_short_circuits_project_verification_when_still_incomplete(monkeypatch):
    # Integration check for the full stream_task wiring, not just the unit
    # function in isolation: an incomplete task_tracker list must prevent
    # project verification from ever running under a false premise of
    # completeness.
    class _Conversation:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.run_calls = 0
            self.state = SimpleNamespace(
                execution_status=ConversationExecutionStatus.FINISHED,
                events=[_task_list_event({"title": "B", "status": "todo"})],
            )

        def send_message(self, message: str) -> None:
            pass

        def run(self) -> None:
            self.run_calls += 1  # stays incomplete across every retry

    verification_calls = {"count": 0}
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: (
            verification_calls.__setitem__("count", verification_calls["count"] + 1)
            or _run(_check(summary="3 passed"))
        ),
    )
    monkeypatch.setattr(runner, "Conversation", _Conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))

    outcome = runner.stream_task(
        "do the thing", cfg=_cfg(verify_tests="always", max_verify_retries=1)
    )

    assert outcome.verification_state == "incomplete"
    assert verification_calls["count"] == 0  # project verification never reached


# --- completion contract -----------------------------------------------------


def test_completion_contract_carries_the_goal_and_checks(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(_check(command="pytest -q", summary="3 passed")),
    )

    conversation = _FakeConversation()
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), lambda _m: None, "build a CLI"
    )

    contract = outcome.completion_contract
    assert contract.goal == "build a CLI"
    assert "pytest -q" in contract.verification_checks
    assert any("pytest -q" in c for c in contract.acceptance_criteria)


def test_completion_contract_notes_limitations_from_skipped_checks(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(
            _check(summary="3 passed"),
            _check(
                name="ruff",
                command="ruff check .",
                primary=False,
                status="unavailable",
                exit_code=None,
                summary="ruff is configured but not installed; lint was not verified",
            ),
        ),
    )

    conversation = _FakeConversation()
    outcome = runner._verify_and_report(
        conversation, _cfg(verify_tests="always"), lambda _m: None, "do the thing"
    )

    assert (
        outcome.verification_state == "verified"
    )  # primary passed; ruff being unavailable doesn't block
    assert any(
        "ruff" in note and "not installed" in note
        for note in outcome.completion_contract.limitations
    )


# --- _verification_followup composes guidance across failing checks --------


def test_verification_followup_nudges_toward_minimal_edit():
    followup = runner._verification_followup(
        _run(_check(status="failed", exit_code=1, summary="1 failed", output="AssertionError: ..."))
    )

    assert "minimal, targeted edit" in followup
    assert "rewriting the whole file" in followup


def test_verification_followup_calls_out_python_syntax_errors_specifically():
    # Regression guard: repeated verification retries on a real project saw
    # the agent do a full-file rewrite to "fix" an IndentationError, which
    # left a new orphaned fragment causing a *different* IndentationError on
    # the next check — file grew, bug moved, never actually fixed.
    output = (
        '  File "hanoi.py", line 85\n'
        "    def move(self, from_rod: int, to_rod: int) -> bool:\n"
        "IndentationError: unexpected indent"
    )
    followup = runner._verification_followup(
        _run(_check(status="failed", exit_code=1, summary="1 error", output=output))
    )

    assert "syntax/indentation error, not a logic bug" in followup
    assert "py_compile" in followup


def test_verification_followup_calls_out_js_syntax_errors_specifically():
    output = (
        "[plugin:vite:oxc] Transform failed with 1 error:\n"
        "[PARSE_ERROR] Adjacent JSX elements must be wrapped in an enclosing tag."
    )
    followup = runner._verification_followup(
        _run(
            _check(
                name="npm run build",
                command="npm run build",
                status="failed",
                exit_code=1,
                summary="build failed",
                output=output,
            )
        )
    )

    assert "JavaScript/TypeScript syntax or parse error" in followup
    assert "enclosing tag or fragment" in followup


def test_verification_followup_omits_syntax_guidance_for_logic_failures():
    followup = runner._verification_followup(
        _run(
            _check(
                status="failed",
                exit_code=1,
                summary="1 failed",
                output="AssertionError: assert not True",
            )
        )
    )

    assert "syntax/indentation error" not in followup


def test_verification_followup_includes_every_failing_check():
    followup = runner._verification_followup(
        _run(
            _check(
                name="pytest",
                status="failed",
                exit_code=1,
                summary="1 failed",
                output="AssertionError",
            ),
            _check(
                name="ruff",
                command="ruff check .",
                primary=False,
                status="failed",
                exit_code=1,
                summary="1 error",
                output="E501",
            ),
        )
    )

    assert "pytest" in followup
    assert "ruff" in followup
    assert "E501" in followup


def test_verification_followup_includes_timed_out_checks_too():
    followup = runner._verification_followup(
        _run(
            _check(
                name="cargo test",
                command="cargo test",
                status="timed_out",
                exit_code=None,
                summary="cargo test exceeded its 300s timeout and was killed",
                output="",
            )
        )
    )

    assert "cargo test" in followup
    assert "hanging" in followup.lower() or "hang" in followup.lower()
    assert "do not simply increase a timeout" in followup


# --- timed_out state and retry behavior -------------------------------------


def test_verification_run_state_timed_out_triggers_retry_and_terminal_timed_out(monkeypatch):
    # Two distinct timeouts (different partial output each time) so this
    # exercises genuine repeated-timeout exhaustion, not "no_progress"
    # (identical signature) covered separately below.
    results = iter(
        [
            _run(
                _check(
                    name="cargo test",
                    command="cargo test",
                    status="timed_out",
                    exit_code=None,
                    output="a",
                )
            ),
            _run(
                _check(
                    name="cargo test",
                    command="cargo test",
                    status="timed_out",
                    exit_code=None,
                    output="b",
                )
            ),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=1),
        emitted.append,
        "do the thing",
    )

    assert conversation.run_calls == 1  # retried once, per max_verify_retries=1
    assert len(emitted) == 1
    assert outcome.verification_state == "timed_out"  # not "retry_exhausted" — a distinct problem
    assert outcome.retries_used == 1


def test_timed_out_check_recovers_on_retry_reports_verified(monkeypatch):
    results = iter(
        [
            _run(
                _check(name="cargo test", command="cargo test", status="timed_out", exit_code=None)
            ),
            _run(_check(name="cargo test", command="cargo test", status="passed")),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=2),
        emitted.append,
        "do the thing",
    )

    assert conversation.run_calls == 1
    assert emitted == []
    assert outcome.verification_state == "verified"
    assert outcome.retries_used == 1


# --- no_progress: a fix attempt that changed nothing observable ------------


def test_no_progress_detected_when_fix_attempt_changes_nothing(monkeypatch):
    # Regression case: an agent edited a comparison operator to "fix" a
    # failing test, but the edit was a no-op for that failure (a different
    # branch handled it) — pytest's output was identical before and after.
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(
            _check(status="failed", exit_code=1, summary="1 failed", output="AssertionError: boom")
        ),
    )

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5),
        emitted.append,
        "do the thing",
    )

    # Stopped after exactly one retry — well before the 5-attempt budget —
    # because that one retry provably changed nothing.
    assert conversation.run_calls == 1
    assert outcome.verification_state == "no_progress"
    assert outcome.retries_used == 1
    assert outcome.success is False
    assert len(emitted) == 1
    notice_text = emitted[0].content[0].text
    assert "no observable change" in notice_text
    assert "1 failed" in notice_text


def test_no_progress_ignores_timing_only_differences(monkeypatch):
    # Two runs whose only difference is a wall-clock duration in the output
    # — must still count as "no progress", not a genuine change.
    results = iter(
        [
            _run(_check(status="failed", exit_code=1, summary="1 failed in 3.85s", output="boom")),
            _run(_check(status="failed", exit_code=1, summary="1 failed in 3.83s", output="boom")),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5),
        emitted.append,
        "do the thing",
    )

    assert outcome.verification_state == "no_progress"
    assert outcome.retries_used == 1


def test_progress_with_a_genuinely_different_failure_does_not_trigger_no_progress(monkeypatch):
    # A different failure each time is real (if unresolved) progress, not
    # "no progress" — must not be misclassified.
    results = iter(
        [
            _run(
                _check(
                    status="failed",
                    exit_code=1,
                    summary="1 failed",
                    output="AssertionError: first bug",
                )
            ),
            _run(
                _check(
                    status="failed",
                    exit_code=1,
                    summary="1 failed",
                    output="AssertionError: second bug",
                )
            ),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=1),
        emitted.append,
        "do the thing",
    )

    assert outcome.verification_state == "retry_exhausted"
    assert conversation.run_calls == 1


def test_no_progress_applies_to_repeated_identical_timeouts_too(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_run_verification",
        lambda _dir, *_a: _run(
            _check(
                name="cargo test",
                command="cargo test",
                status="timed_out",
                exit_code=None,
                output="hang",
            )
        ),
    )

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=5),
        emitted.append,
        "do the thing",
    )

    assert outcome.verification_state == "no_progress"
    assert outcome.retries_used == 1


# --- max_iteration_per_run is actually wired to Conversation ---------------


class _FakeWorkspaceCM:
    """Minimal context manager standing in for `build_workspace`'s return
    value (`nullcontext(...)` for local execution, `DockerWorkspace` for
    docker) — only `__enter__`/`__exit__` matter here.
    """

    def __init__(self, value: str) -> None:
        self._value = value

    def __enter__(self) -> str:
        return self._value

    def __exit__(self, *exc_info: object) -> bool:
        return False


class _RecordingConversation:
    """Stands in for `openhands.sdk.Conversation`, recording the kwargs each
    instance was constructed with (via the class-level `instances` list)
    instead of driving a real LLM loop.
    """

    instances: ClassVar[list[_RecordingConversation]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.state = SimpleNamespace(
            execution_status=ConversationExecutionStatus.FINISHED, events=[]
        )
        _RecordingConversation.instances.append(self)

    def send_message(self, message: str) -> None:
        pass

    def run(self) -> None:
        pass


def test_stream_task_wires_max_iterations_to_conversation(monkeypatch):
    # Regression guard: CERTO_MAX_ITERATIONS was parsed/validated by
    # config.py from Milestone 1 onward but never actually passed to
    # Conversation(...), so every run silently used the SDK's own default
    # (500) regardless of .env — contrary to docs/SPEC.md section 12's
    # acceptance criterion ("CERTO_MAX_ITERATIONS reliably bounds runaway
    # loops"). Found only by reading runner.py directly, not by any test —
    # this asserts the kwarg is actually threaded through, so a future
    # regression (e.g. an SDK upgrade renaming/removing the kwarg) fails
    # loudly here instead of silently reverting to an unbounded default.
    _RecordingConversation.instances = []
    monkeypatch.setattr(runner, "Conversation", _RecordingConversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: _FakeWorkspaceCM("fake-workspace"))

    outcome = runner.stream_task("do the thing", cfg=_cfg(verify_tests="never", max_iterations=17))

    assert outcome.verification_state == "inconclusive"  # verify_tests="never" short-circuits
    assert len(_RecordingConversation.instances) == 1
    kwargs = _RecordingConversation.instances[0].kwargs
    assert kwargs["max_iteration_per_run"] == 17
    assert kwargs["agent"] == "fake-agent"
    assert kwargs["workspace"] == "fake-workspace"


def test_no_progress_check_does_not_apply_after_successful_recovery(monkeypatch):
    # A retry that fixes the problem must never be second-guessed by the
    # no-progress check — "verified" isn't in _RETRIABLE_STATES, so the
    # signature comparison shouldn't even run.
    results = iter(
        [
            _run(_check(status="failed", exit_code=1, summary="1 failed", output="boom")),
            _run(_check(status="passed", summary="3 passed")),
        ]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    conversation = _FakeConversation()
    emitted = []
    outcome = runner._verify_and_report(
        conversation,
        _cfg(verify_tests="always", max_verify_retries=2),
        emitted.append,
        "do the thing",
    )

    assert outcome.verification_state == "verified"
    assert emitted == []


# --- _apply_acceptance_checks: caller-supplied acceptance criteria ---------


def _outcome(verification_state: str = "verified") -> runner.TaskOutcome:
    contract = runner.CompletionContract(
        goal="do the thing", acceptance_criteria=[], verification_checks=[], limitations=[]
    )
    return runner.TaskOutcome(verification_state=verification_state, completion_contract=contract)


def test_apply_acceptance_checks_is_a_noop_when_none_given(tmp_path):
    outcome = _outcome()

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), lambda _m: None, None
    )

    assert result is outcome


def test_apply_acceptance_checks_is_a_noop_when_empty_list(tmp_path):
    outcome = _outcome()

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), lambda _m: None, []
    )

    assert result is outcome


def test_apply_acceptance_checks_all_pass_keeps_verified(tmp_path):
    (tmp_path / "README.md").write_text("# Usage\n...")
    outcome = _outcome("verified")
    checks = [AcceptanceCheck(kind="file_exists", path="README.md")]

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), lambda _m: None, checks
    )

    assert result.verification_state == "verified"
    assert len(result.acceptance_results) == 1
    assert result.acceptance_results[0].passed is True
    assert result.completion_contract.limitations == []
    assert any("README.md" in c for c in result.completion_contract.acceptance_criteria)


def test_apply_acceptance_checks_required_failure_downgrades_verified(tmp_path):
    outcome = _outcome("verified")
    checks = [AcceptanceCheck(kind="file_exists", path="OUTPUT.txt", description="the output file")]
    emitted = []

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), emitted.append, checks
    )

    assert result.verification_state == "acceptance_failed"
    assert result.acceptance_results[0].passed is False
    assert any("the output file" in note for note in result.completion_contract.limitations)
    assert len(emitted) == 1
    assert "acceptance check" in emitted[0].content[0].text.lower()


def test_apply_acceptance_checks_optional_failure_does_not_downgrade(tmp_path):
    outcome = _outcome("verified")
    checks = [AcceptanceCheck(kind="file_exists", path="OUTPUT.txt", required=False)]
    emitted = []

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), emitted.append, checks
    )

    assert result.verification_state == "verified"  # unaffected — the check wasn't required
    assert result.acceptance_results[0].passed is False
    assert any(
        "Optional acceptance check failed" in note
        for note in result.completion_contract.limitations
    )
    assert emitted == []  # no give-up notice — nothing was blocked


def test_apply_acceptance_checks_does_not_override_a_non_verified_state(tmp_path):
    # A run that already ended in some other failure state (retry_exhausted,
    # stuck, etc.) has nothing left to "block" — acceptance results are
    # still attached for visibility, but the original state is preserved.
    outcome = _outcome("retry_exhausted")
    checks = [AcceptanceCheck(kind="file_exists", path="OUTPUT.txt")]

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), lambda _m: None, checks
    )

    assert result.verification_state == "retry_exhausted"
    assert result.acceptance_results[0].passed is False


def test_apply_acceptance_checks_rejects_a_path_escape_without_crashing(tmp_path):
    # evaluate_acceptance_check turns a rejected path into a failed result,
    # not an exception — _apply_acceptance_checks must not need to know that.
    outcome = _outcome("verified")
    checks = [AcceptanceCheck(kind="file_exists", path="/etc/passwd", required=True)]

    result = runner._apply_acceptance_checks(
        outcome, _cfg(workspace=str(tmp_path)), lambda _m: None, checks
    )

    assert result.verification_state == "acceptance_failed"
    assert result.acceptance_results[0].passed is False
    assert "absolute" in result.acceptance_results[0].detail


def test_stream_task_applies_acceptance_checks_end_to_end(monkeypatch, tmp_path):
    (tmp_path / "OUTPUT.txt").write_text("done")
    conversation = _RecordingConversation()
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state="verified",
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path)),
        acceptance_checks=[AcceptanceCheck(kind="file_exists", path="OUTPUT.txt")],
    )

    assert outcome.verification_state == "verified"
    assert len(outcome.acceptance_results) == 1
    assert outcome.acceptance_results[0].passed is True


def test_stream_task_acceptance_check_failure_downgrades_a_real_verified_run(monkeypatch, tmp_path):
    conversation = _RecordingConversation()
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state="verified",
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path)),
        acceptance_checks=[AcceptanceCheck(kind="file_exists", path="OUTPUT.txt")],
    )

    assert outcome.verification_state == "acceptance_failed"


# --- CERTO_MODEL_SELECTION=auto -------------------------------------------


class _FakeMetrics:
    def __init__(self, cost: float = 0.01) -> None:
        self._cost = cost

    def get(self) -> dict:
        return {"accumulated_cost": self._cost}


class _FakeConversationStats:
    def __init__(self) -> None:
        self.usage_to_metrics = {"certo": _FakeMetrics()}

    def get_combined_metrics(self) -> _FakeMetrics:
        return _FakeMetrics(sum(m._cost for m in self.usage_to_metrics.values()))


class _SwitchableConversation:
    """Fake Conversation for model-selection tests: tracks switch_llm calls
    and can be told to raise on a given .run() call (simulating a
    ConversationRunError from a real provider failure) or just transition
    execution_status normally.

    `run_results`: one entry consumed per `.run()` call — `None` (status
    unchanged), a `ConversationExecutionStatus` (status set to it), or a
    `BaseException` instance (raised). Once exhausted, further calls leave
    status unchanged.
    """

    def __init__(
        self,
        run_results: list,
        *,
        initial_status: ConversationExecutionStatus = ConversationExecutionStatus.FINISHED,
    ) -> None:
        self._run_results = list(run_results)
        self.state = SimpleNamespace(execution_status=initial_status, events=[])
        self.run_calls = 0
        self.sent_messages: list[str] = []
        self.switched_llms: list = []
        self.conversation_stats = _FakeConversationStats()

    def send_message(self, message: str) -> None:
        self.sent_messages.append(message)

    def run(self) -> None:
        self.run_calls += 1
        if not self._run_results:
            return
        result = self._run_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if result is not None:
            self.state.execution_status = result

    def switch_llm(self, llm) -> None:
        self.switched_llms.append(llm)


def _run_error(message: str = "rate limited") -> Exception:
    # A real openhands.sdk.llm.exceptions.types.LLMError, wrapped exactly the
    # way LocalConversation.run() actually wraps every LLM-call failure —
    # confirmed live (a real conversation.run() against a deliberately
    # invalid API key) that this, not a bare LiteLLM/openai exception, is
    # what .original_exception actually is. See runner.py's
    # _run_conversation_once docstring for the two wrong guesses first.
    from openhands.sdk.conversation.exceptions import ConversationRunError
    from openhands.sdk.llm.exceptions.types import LLMRateLimitError

    return ConversationRunError("conv-test", LLMRateLimitError(message))


_MODEL_CATALOG_YAML = """
models:
  - name: cheap
    model: openai/gpt-4o-mini
    ratings: {reasoning: 2, cost: 5}
  - name: balanced
    model: anthropic/claude-sonnet-4-5-20250929
    ratings: {reasoning: 4, cost: 3}
  - name: strong
    model: anthropic/claude-opus-4
    ratings: {reasoning: 5, cost: 1}

task_profiles:
  default:
    weights: {reasoning: 1, cost: 1}
"""


def _catalog_files(tmp_path) -> dict[str, str]:
    """Config fields naming the model files, written from the catalog."""
    from model_file_helpers import model_file_config

    return model_file_config(tmp_path, _MODEL_CATALOG_YAML)


def _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path):
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state="verified",
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )


def test_auto_mode_off_never_loads_a_catalog(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    def _fail_if_called(_path):
        raise AssertionError("the catalog should not be loaded when model_selection=manual")

    monkeypatch.setattr(runner, "load_checked_catalog", _fail_if_called)

    outcome = runner.stream_task(
        "do the thing", cfg=_cfg(workspace=str(tmp_path), model_selection="manual")
    )

    assert outcome.model_decisions == ()


def test_auto_mode_picks_the_best_fit_candidate_for_the_initial_run(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    captured_agent_cfg = {}

    def _fake_build_agent(cfg, **kwargs):
        captured_agent_cfg["cfg"] = cfg
        captured_agent_cfg["usage_id"] = kwargs.get("usage_id")
        return "fake-agent"

    monkeypatch.setattr(runner, "build_agent", _fake_build_agent)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_catalog_files(tmp_path),
        ),
    )

    # weights {reasoning: 1, cost: 1} -> cheap scores 7, balanced 7, strong 6
    # (cheap and balanced tie at 7; cheap is declared first, wins the tie —
    # Python's sort is stable, ties keep their original relative order).
    assert captured_agent_cfg["cfg"].model == "openai/gpt-4o-mini"
    assert captured_agent_cfg["usage_id"] == "certo:cheap"
    assert len(outcome.model_decisions) == 1
    assert outcome.model_decisions[0].kind == "initial"
    assert outcome.model_decisions[0].chosen == "cheap (effort default)"
    assert outcome.model_decisions[0].chosen_name == "cheap"


def test_auto_mode_uses_a_catalog_it_is_given(monkeypatch, tmp_path):
    # The benchmark passes its own catalog, narrowed to an arm's models.
    from dataclasses import replace as dc_replace

    from certo.catalog_check import load_checked_catalog

    files = _catalog_files(tmp_path)
    loaded = load_checked_catalog(files["models_file"], files["models_list_file"])
    narrowed = dc_replace(loaded, models=[m for m in loaded.models if m.name == "strong"])
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    def _must_not_load(*_a, **_k):
        raise AssertionError("a given catalog must not be loaded again")

    monkeypatch.setattr(runner, "load_checked_catalog", _must_not_load)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path), model_selection="auto"),
        model_catalog=narrowed,
    )

    assert [d.chosen_name for d in outcome.model_decisions] == ["strong"]


def test_auto_mode_writes_model_decisions_to_the_workspace(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path), model_selection="auto", **_catalog_files(tmp_path)),
    )

    content = (tmp_path / "MODEL_DECISIONS.md").read_text()
    assert "# Model Decisions" in content
    assert "initial" in content


def test_auto_mode_interactive_prompts_for_the_initial_choice(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    captured_agent_cfg = {}
    monkeypatch.setattr(
        runner,
        "build_agent",
        lambda cfg, **kw: captured_agent_cfg.setdefault("cfg", cfg) and "fake-agent",
    )
    prompts = []

    def on_model_choice(candidates, recommended_index, reason):
        prompts.append((tuple(c.name for c in candidates), recommended_index, reason))
        return 2  # deliberately pick the last (weakest-fit) candidate

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_catalog_files(tmp_path),
            interactive=True,
        ),
        on_model_choice=on_model_choice,
    )

    assert len(prompts) == 1
    assert prompts[0][0] == ("cheap", "balanced", "strong")  # full ranked order
    assert prompts[0][1] == 0  # recommended index is always the top-ranked one
    assert (
        outcome.model_decisions[0].chosen == "strong (effort default)"
    )  # index 2 of the ranked list


def test_api_failure_triggers_a_switch_to_the_next_candidate(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([_run_error("auth failed"), None])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_catalog_files(tmp_path),
            execution="local",
        ),
    )

    assert conversation.run_calls == 2
    assert len(conversation.switched_llms) == 1
    kinds = [d.kind for d in outcome.model_decisions]
    assert kinds == ["initial", "escalation_api_failure"]
    assert outcome.verification_state == "verified"


def _pinned_catalog_files(tmp_path) -> dict[str, str]:
    """The test catalog, with `default` pinned to `strong` (which the
    weights rank last)."""
    from model_file_helpers import model_file_config

    yaml_text = _MODEL_CATALOG_YAML.replace("  default:\n", "  default:\n    model: strong\n")
    return model_file_config(tmp_path, yaml_text)


def test_auto_mode_runs_the_profiles_pinned_model_first(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path), model_selection="auto", **_pinned_catalog_files(tmp_path)
        ),
    )

    decision = outcome.model_decisions[0]
    assert decision.chosen == "strong (effort default)"
    assert "the profile names strong; fallbacks ranked by weights" in decision.reason


def test_after_the_pinned_model_fails_the_weights_pick_the_next(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([_run_error("auth failed"), None])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_pinned_catalog_files(tmp_path),
            execution="local",
        ),
    )

    assert [d.chosen for d in outcome.model_decisions] == [
        "strong (effort default)",
        "cheap (effort default)",
    ]
    assert outcome.verification_state == "verified"


def test_api_failure_reraises_once_the_chain_is_exhausted(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([_run_error("e1"), _run_error("e2"), _run_error("e3")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    with pytest.raises(Exception, match="e3"):
        runner.stream_task(
            "do the thing",
            cfg=_cfg(
                workspace=str(tmp_path),
                model_selection="auto",
                **_catalog_files(tmp_path),
                execution="local",
            ),
        )

    assert conversation.run_calls == 3  # tried all three candidates, then gave up


def test_model_decisions_are_written_even_when_the_chain_is_exhausted_and_raises(
    monkeypatch, tmp_path
):
    # Regression test: caught live — the first implementation only wrote
    # MODEL_DECISIONS.md after a normal return, so a task that ultimately
    # raised (every candidate failed) lost its entire escalation history —
    # exactly the case where it matters most for debugging.
    conversation = _SwitchableConversation([_run_error("e1"), _run_error("e2")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    # Only two candidates, so the chain is fully exhausted after two failures.
    from model_file_helpers import write_model_files

    list_path, models_path = write_model_files(
        tmp_path,
        "models:\n"
        "  - name: cheap\n    model: openai/gpt-4o-mini\n    ratings: {reasoning: 2}\n"
        "  - name: balanced\n    model: anthropic/claude-sonnet-4-5-20250929\n"
        "    ratings: {reasoning: 4}\n",
    )

    with pytest.raises(Exception, match="e2"):
        runner.stream_task(
            "do the thing",
            cfg=_cfg(
                workspace=str(tmp_path),
                model_selection="auto",
                models_file=models_path,
                models_list_file=list_path,
                execution="local",
            ),
        )

    content = (tmp_path / "MODEL_DECISIONS.md").read_text()
    assert "initial" in content
    assert "escalation_api_failure" in content
    assert "e1" in content


def test_api_failure_does_not_switch_under_docker_execution(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([_run_error("auth failed")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))

    with pytest.raises(Exception, match="auth failed"):
        runner.stream_task(
            "do the thing",
            cfg=_cfg(
                workspace=str(tmp_path),
                model_selection="auto",
                **_catalog_files(tmp_path),
                execution="docker",
            ),
        )

    assert conversation.switched_llms == []


def test_a_non_api_exception_never_triggers_a_model_switch(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([RuntimeError("a real bug, not a provider problem")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    with pytest.raises(RuntimeError, match="a real bug"):
        runner.stream_task(
            "do the thing",
            cfg=_cfg(
                workspace=str(tmp_path),
                model_selection="auto",
                **_catalog_files(tmp_path),
                execution="local",
            ),
        )

    assert conversation.switched_llms == []


def test_a_failed_run_carries_the_usage_it_recorded_on_its_exception(monkeypatch, tmp_path):
    # `certo bench` reads this attribute to record what an interrupted run
    # spent; see bench.execute_run and issue #30.
    conversation = _SwitchableConversation([RuntimeError("provider down")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    with pytest.raises(RuntimeError, match="provider down") as info:
        runner.stream_task(
            "do the thing",
            cfg=_cfg(workspace=str(tmp_path), model_selection="auto", **_catalog_files(tmp_path)),
        )

    summary = info.value.run_summary
    assert isinstance(summary, RunSummary)
    # The fake conversation records no tokens: zeros, not a missing summary.
    assert summary.total_tokens == 0 and summary.condensations == 0


def test_quality_failure_escalates_during_verify_retry(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([None, None])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)

    failing = _run(_check(status="failed", summary="1 failed"))
    passing = _run(_check(status="passed", summary="1 passed"))
    results = iter([failing, passing])
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_catalog_files(tmp_path),
            execution="local",
        ),
    )

    assert len(conversation.switched_llms) == 1
    kinds = [d.kind for d in outcome.model_decisions]
    assert kinds == ["initial", "escalation_quality_failure"]
    assert outcome.verification_state == "verified"


def test_auto_model_switches_after_a_step_limit_stop_with_failing_checks(monkeypatch, tmp_path):
    # Option (a): a step-limit stop whose checks fail is a failed attempt,
    # so --auto-model moves to the next model, which gets fresh steps.
    conversation = _SwitchableConversation(
        [ConversationExecutionStatus.ERROR, ConversationExecutionStatus.FINISHED]
    )
    conversation.state.events.append(_step_limit_event())
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(str(tmp_path)))
    results = iter(
        [_run(_check(status="failed", summary="1 failed")), _run(_check(status="passed"))]
    )
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: next(results))

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            model_selection="auto",
            **_catalog_files(tmp_path),
            execution="local",
        ),
    )

    assert [d.kind for d in outcome.model_decisions] == ["initial", "escalation_quality_failure"]
    assert len(conversation.switched_llms) == 1
    assert outcome.verification_state == "verified"


# --- CERTO_ARTIFACTS_DIR ---------------------------------------------


def test_artifacts_dir_unset_writes_nothing(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)

    runner.stream_task("do the thing", cfg=_cfg(workspace=str(tmp_path)))

    assert not (tmp_path / "artifacts").exists()


def test_artifacts_dir_set_writes_metadata_transcript_and_metrics(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    artifacts_dir = tmp_path / "artifacts"

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path), artifacts_dir=str(artifacts_dir)),
        project="my-project",
    )

    run_dirs = list((artifacts_dir / "my-project").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    metadata = json.loads((run_dir / "metadata.json").read_text())
    assert metadata["project"] == "my-project"
    assert metadata["task"] == "do the thing"
    assert metadata["verification_state"] == outcome.verification_state
    assert metadata["error"] is None
    assert (run_dir / "transcript.json").exists()
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["combined"]["accumulated_cost"] == 0.01
    assert "certo" in metrics["per_model"]


def test_the_run_record_holds_the_verdict_after_the_acceptance_checks(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    _mock_task_tracker_and_verify(monkeypatch, verification_state="verified")
    artifacts_dir = tmp_path / "artifacts"

    outcome = runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path), artifacts_dir=str(artifacts_dir)),
        project="my-project",
        acceptance_checks=[AcceptanceCheck(kind="file_exists", path="MISSING.txt")],
    )

    (run_dir,) = (artifacts_dir / "my-project").iterdir()
    metadata = json.loads((run_dir / "metadata.json").read_text())
    assert outcome.verification_state == "acceptance_failed"
    assert metadata["verification_state"] == "acceptance_failed"


def test_artifacts_dir_uses_unscoped_bucket_with_no_project(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    artifacts_dir = tmp_path / "artifacts"

    runner.stream_task(
        "do the thing", cfg=_cfg(workspace=str(tmp_path), artifacts_dir=str(artifacts_dir))
    )

    assert (artifacts_dir / "_unscoped").is_dir()


def test_artifacts_dir_uses_the_given_run_id_verbatim(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    artifacts_dir = tmp_path / "artifacts"

    runner.stream_task(
        "do the thing",
        cfg=_cfg(workspace=str(tmp_path), artifacts_dir=str(artifacts_dir)),
        run_id="my-explicit-run-id",
    )

    assert (artifacts_dir / "_unscoped" / "my-explicit-run-id" / "metadata.json").exists()


def test_artifacts_are_written_even_when_the_task_raises(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([_run_error("boom")])
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(Exception, match="boom"):
        runner.stream_task(
            "do the thing",
            cfg=_cfg(
                workspace=str(tmp_path),
                artifacts_dir=str(artifacts_dir),
                # No auto-selection here — a plain, unhandled failure.
            ),
        )

    run_dirs = list((artifacts_dir / "_unscoped").iterdir())
    assert len(run_dirs) == 1
    metadata = json.loads((run_dirs[0] / "metadata.json").read_text())
    assert metadata["verification_state"] is None
    assert "boom" in metadata["error"]
    assert metadata["run_summary"]["duration_seconds"] >= 0  # still recorded on failure


def test_artifacts_metrics_include_per_model_breakdown_after_a_switch(monkeypatch, tmp_path):
    conversation = _SwitchableConversation([])
    conversation.conversation_stats.usage_to_metrics = {
        "certo:cheap": _FakeMetrics(0.01),
        "certo:balanced": _FakeMetrics(0.02),
    }
    _stub_stream_task_dependencies(monkeypatch, conversation, tmp_path)
    artifacts_dir = tmp_path / "artifacts"

    runner.stream_task(
        "do the thing",
        cfg=_cfg(
            workspace=str(tmp_path),
            artifacts_dir=str(artifacts_dir),
            model_selection="auto",
            **_catalog_files(tmp_path),
        ),
    )

    run_dirs = list((artifacts_dir / "_unscoped").iterdir())
    metrics = json.loads((run_dirs[0] / "metrics.json").read_text())
    assert metrics["combined"]["accumulated_cost"] == 0.03
    assert set(metrics["per_model"]) == {"certo:cheap", "certo:balanced"}
    metadata = json.loads((run_dirs[0] / "metadata.json").read_text())
    assert metrics["summary"] == metadata["run_summary"]
    assert round(metadata["run_summary"]["total_cost"], 6) == 0.03
    assert len(metadata["run_summary"]["models"]) == 2
    assert metadata["run_summary"]["duration_seconds"] >= 0


# --- Project environment before the agent starts -----------------------------


def _stub_for_env_tests(monkeypatch, captured):
    conversation = _ConfirmConversation([ConversationExecutionStatus.FINISHED])
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(
        runner, "build_agent", lambda cfg, **kw: captured.update(kw) or "fake-agent"
    )
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(cfg.workspace))
    monkeypatch.setattr(runner, "_enforce_task_tracker_completion", lambda *a, **kw: None)
    monkeypatch.setattr(
        runner,
        "_verify_and_report",
        lambda *a, **kw: runner.TaskOutcome(
            verification_state="inconclusive",
            completion_contract=runner.CompletionContract(
                goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
            ),
        ),
    )


def test_stream_task_gives_a_python_project_its_env_in_the_agents_terminal(
    monkeypatch, tmp_path, project_venv
):
    venv = project_venv(tmp_path)
    (tmp_path / "app.py").write_text("print('hi')\n")
    captured: dict = {}
    _stub_for_env_tests(monkeypatch, captured)

    runner.stream_task("fix the bug", cfg=_cfg(workspace=str(tmp_path)))

    assert captured["project_env"].host_dir == venv
    assert captured["terminal_env"]["VIRTUAL_ENV"] == venv
    scripts = "Scripts" if os.name == "nt" else "bin"
    first_path = captured["terminal_env"]["PATH"].split(os.pathsep)[0]
    assert os.path.normpath(first_path) == os.path.join(venv, scripts)


def test_stream_task_creates_no_env_for_a_node_project(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    captured: dict = {}
    _stub_for_env_tests(monkeypatch, captured)

    runner.stream_task("Add a Python helper script", cfg=_cfg(workspace=str(tmp_path)))

    assert captured["project_env"] is None
    assert not (tmp_path / ".venv").exists()


def test_stream_task_creates_an_env_for_an_empty_workspace_with_a_python_task(
    monkeypatch, tmp_path
):
    captured: dict = {}
    emitted: list = []
    _stub_for_env_tests(monkeypatch, captured)

    runner.stream_task(
        "Create hello.py that prints hello, plus a pytest test for it",
        cfg=_cfg(workspace=str(tmp_path)),
        on_message=emitted.append,
    )

    assert captured["project_env"].host_dir == str(tmp_path / ".venv")
    assert (tmp_path / ".venv").is_dir()
    assert any("Created the project environment" in m.content[0].text for m in emitted)


# --- .certo/ run state and resume (project_state.py) -------------------------


def _verified_outcome() -> runner.TaskOutcome:
    return runner.TaskOutcome(
        verification_state="retry_exhausted",
        completion_contract=runner.CompletionContract(
            goal="", acceptance_criteria=[], verification_checks=[], limitations=["no mypy"]
        ),
        checks=(_check(status="failed", exit_code=1, output="E   assert 2 == 3"),),
        retries_used=2,
    )


def _stub_for_state_tests(monkeypatch, outcome=None, raise_in_phases=None):
    _RecordingConversation.instances = []
    monkeypatch.setattr(runner, "Conversation", _RecordingConversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext(cfg.workspace))
    sent: list = []

    def fake_phases(conversation, cfg, emit, task, *args, **_kwargs):
        first_message = args[6]
        sent.append(first_message or task)
        if raise_in_phases is not None:
            raise raise_in_phases
        return outcome or _verified_outcome()

    monkeypatch.setattr(runner, "_run_stream_task_phases", fake_phases)
    return sent


def test_stream_task_without_save_state_leaves_no_certo_folder(monkeypatch, tmp_path):
    _stub_for_state_tests(monkeypatch)

    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)))

    assert not (tmp_path / ".certo").exists()
    assert "persistence_dir" not in _RecordingConversation.instances[0].kwargs


def test_stream_task_saves_the_conversation_and_the_final_verdict(monkeypatch, tmp_path):
    _stub_for_state_tests(monkeypatch)

    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), save_state=True)

    kwargs = _RecordingConversation.instances[0].kwargs
    assert kwargs["persistence_dir"] == str(tmp_path / ".certo" / "conversations")
    from certo.project_state import load_record

    record = load_record(str(tmp_path))
    assert record.task == "do it"
    assert record.conversation_id == kwargs["conversation_id"].hex
    assert record.status == "finished"
    assert record.verdict == "retry_exhausted"
    assert record.retries_used == 2
    assert record.checks[0].output_tail == "E   assert 2 == 3"
    assert record.limitations == ["no mypy"]
    assert "verdict `retry_exhausted`" in (tmp_path / ".certo" / "STATUS.md").read_text()


def test_a_condensation_is_announced_and_counted(monkeypatch, tmp_path):
    from openhands.sdk.event import Condensation

    _stub_for_state_tests(monkeypatch)
    notices: list = []
    monkeypatch.setattr(runner, "_emit_notice", lambda _emit, text: notices.append(text))

    def fake_phases(conversation, cfg, emit, task, *args, **_kwargs):
        (callback,) = conversation.kwargs["callbacks"]
        callback(
            Condensation(
                forgotten_event_ids=set(), summary="s", summary_offset=1, llm_response_id="r"
            )
        )
        return _verified_outcome()

    monkeypatch.setattr(runner, "_run_stream_task_phases", fake_phases)
    outcome = runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)))

    assert outcome.run_summary.condensations == 1
    assert any("older steps were summarized" in n for n in notices)


@pytest.mark.parametrize(
    ("window", "warn_at", "warned"),
    [(24576, 32768, True), (32768, 32768, False), (None, 32768, False), (24576, 0, False)],
)
def test_a_small_known_window_is_warned_about_before_the_agent(
    monkeypatch, tmp_path, window, warn_at, warned
):
    from certo import context_window

    _stub_for_state_tests(monkeypatch)
    notices: list = []
    monkeypatch.setattr(runner, "_emit_notice", lambda _emit, text: notices.append(text))
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: window)
    monkeypatch.setattr(runner, "_run_stream_task_phases", lambda *a, **k: _verified_outcome())
    cfg = _cfg(workspace=str(tmp_path), model="ollama/qwen3.8:27b", context_warn_tokens=warn_at)

    runner.stream_task("do it", cfg=cfg)

    found = [n for n in notices if "CERTO_CONTEXT_WARN_TOKENS" in n]
    assert bool(found) is warned
    if warned:
        assert found[0].startswith("Certo: ollama/qwen3.8:27b has a context window of 24,576")


def _checkpoint_run(monkeypatch, tmp_path, **kwargs):
    from certo import checkpoints

    if not checkpoints.git_available():
        pytest.skip("git isn't installed")
    _stub_for_state_tests(monkeypatch)
    (tmp_path / "a.py").write_text("a = 1\n")

    def fake_phases(conversation, cfg, emit, task, *args, **_kwargs):
        (tmp_path / "a.py").write_text("a = 2\n")
        args[7](SimpleNamespace(state="failed", checks=[]))
        (tmp_path / "a.py").write_text("a = 3\n")
        args[7](SimpleNamespace(state="verified", checks=[]))
        return _verified_outcome()

    monkeypatch.setattr(runner, "_run_stream_task_phases", fake_phases)
    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), **kwargs)
    return [c.label for c in checkpoints.list_checkpoints(str(tmp_path))]


def test_a_run_that_saves_state_takes_checkpoints(monkeypatch, tmp_path):
    labels = _checkpoint_run(monkeypatch, tmp_path, save_state=True)

    # The last check run already holds the final files: no extra snapshot.
    assert labels == ["before the agent", "checks 1: failed", "checks 2: verified"]


def test_no_checkpoints_without_saved_state_or_when_turned_off(monkeypatch, tmp_path):
    assert _checkpoint_run(monkeypatch, tmp_path) == []
    assert not (tmp_path / ".certo").exists()


def test_checkpoints_can_be_turned_off(monkeypatch, tmp_path):
    from certo import checkpoints

    if not checkpoints.git_available():
        pytest.skip("git isn't installed")
    _stub_for_state_tests(monkeypatch)

    runner.stream_task(
        "do it", cfg=_cfg(workspace=str(tmp_path), checkpoints=False), save_state=True
    )

    assert checkpoints.list_checkpoints(str(tmp_path)) == []


@pytest.mark.parametrize(
    ("error", "status"), [(KeyboardInterrupt(), "interrupted"), (RuntimeError("boom"), "error")]
)
def test_stream_task_records_an_interrupted_or_failed_run(monkeypatch, tmp_path, error, status):
    from certo.project_state import load_record

    _stub_for_state_tests(monkeypatch, raise_in_phases=error)

    with pytest.raises(type(error)):
        runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), save_state=True)

    record = load_record(str(tmp_path))
    assert record.status == status
    assert record.verdict is None


def test_docker_runs_save_the_record_but_not_the_conversation(monkeypatch, tmp_path):
    from certo.project_state import load_record

    _stub_for_state_tests(monkeypatch)

    runner.stream_task(
        "do it", cfg=_cfg(workspace=str(tmp_path), execution="docker"), save_state=True
    )

    assert "persistence_dir" not in _RecordingConversation.instances[0].kwargs
    assert load_record(str(tmp_path)).verdict == "retry_exhausted"


def test_resume_reloads_the_saved_conversation(monkeypatch, tmp_path):
    from certo.project_state import load_record

    sent = _stub_for_state_tests(monkeypatch)
    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), save_state=True)
    first = load_record(str(tmp_path))
    # Stand in for the SDK's own saved conversation.
    saved = tmp_path / ".certo" / "conversations" / first.conversation_id
    saved.mkdir(parents=True)
    (saved / "base_state.json").write_text("{}")

    runner.stream_task(
        first.task,
        cfg=_cfg(workspace=str(tmp_path)),
        resume_from=first,
        resume_instruction="the tests use port 8080",
    )

    kwargs = _RecordingConversation.instances[-1].kwargs
    assert kwargs["conversation_id"].hex == first.conversation_id
    assert "being resumed" in sent[-1]
    assert "the tests use port 8080" in sent[-1]
    assert "E   assert 2 == 3" in sent[-1]  # the last failing output, from STATUS.md
    record = load_record(str(tmp_path))
    assert record.resumes == 1
    assert record.status == "finished"


def test_resume_without_a_saved_conversation_starts_fresh_with_the_task(monkeypatch, tmp_path):
    from certo.project_state import load_record

    sent = _stub_for_state_tests(monkeypatch)
    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), save_state=True)
    first = load_record(str(tmp_path))
    emitted: list = []

    runner.stream_task(
        first.task,
        cfg=_cfg(workspace=str(tmp_path)),
        on_message=emitted.append,
        resume_from=first,
    )

    kwargs = _RecordingConversation.instances[-1].kwargs
    assert kwargs["conversation_id"].hex != first.conversation_id
    assert "conversation isn't available" in sent[-1]
    assert "do it" in sent[-1]
    assert any("resuming without the earlier conversation" in m.content[0].text for m in emitted)


def test_resume_falls_back_when_the_sdk_refuses_the_saved_conversation(monkeypatch, tmp_path):
    from certo.project_state import load_record

    sent = _stub_for_state_tests(monkeypatch)
    runner.stream_task("do it", cfg=_cfg(workspace=str(tmp_path)), save_state=True)
    first = load_record(str(tmp_path))
    saved = tmp_path / ".certo" / "conversations" / first.conversation_id
    saved.mkdir(parents=True)
    (saved / "base_state.json").write_text("{}")

    class _Refusing(_RecordingConversation):
        def __init__(self, **kwargs):
            if kwargs.get("conversation_id") is not None and (
                kwargs["conversation_id"].hex == first.conversation_id
            ):
                raise ValueError("tools don't match")
            super().__init__(**kwargs)

    monkeypatch.setattr(runner, "Conversation", _Refusing)

    runner.stream_task(first.task, cfg=_cfg(workspace=str(tmp_path)), resume_from=first)

    assert "conversation isn't available" in sent[-1]


def test_a_real_sdk_conversation_resumes_from_certo_and_never_saves_the_key(tmp_path):
    """No model call: building a Conversation writes its state, and building
    it again with the same id loads it."""
    cfg = _cfg(workspace=str(tmp_path), api_key="sk-THIS-MUST-NOT-BE-SAVED")
    first_messages: list = []

    def new_conversation(**persistence):
        return runner.Conversation(
            agent=runner.build_agent(cfg),
            workspace=str(tmp_path),
            max_iteration_per_run=cfg.max_iterations,
            **persistence,
        )

    conversation, writer, first_message = runner._open_saved_conversation(
        new_conversation, cfg, "do it", cfg.model, None, None, None, first_messages.append
    )
    assert first_message is None
    conversation.send_message("remember this: PROBE-42")
    record = writer.record

    resumed, _writer, message = runner._open_saved_conversation(
        new_conversation,
        cfg,
        "do it",
        "anthropic/other-model",
        "high",
        record,
        None,
        first_messages.append,
    )

    assert "being resumed" in message
    assert _writer.record.reasoning_effort == "high"
    texts = [str(event) for event in resumed.state.events]
    assert any("PROBE-42" in text for text in texts)
    assert first_messages == []  # no fallback notice
    saved = "".join(
        p.read_text(errors="ignore") for p in (tmp_path / ".certo").rglob("*") if p.is_file()
    )
    assert "PROBE-42" in saved
    assert "sk-THIS-MUST-NOT-BE-SAVED" not in saved


# --- unchanged: verified checks, but the agent changed no file ---------------


class _EditingConversation(_FakeConversation):
    """A fake conversation whose `run()` calls write the given files, one
    dict per call (an empty dict changes nothing)."""

    def __init__(self, workspace, writes_per_run: list[dict]) -> None:
        super().__init__()
        self.workspace = workspace
        self.writes_per_run = list(writes_per_run)

    def run(self) -> None:
        super().run()
        for name, text in (self.writes_per_run.pop(0) if self.writes_per_run else {}).items():
            (self.workspace / name).write_text(text)


def _phases(monkeypatch, tmp_path, writes_per_run, *, check_changes=True):
    monkeypatch.setattr(runner, "_agent_changed_files", _REAL_AGENT_CHANGED_FILES)
    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(summary="3 passed"))
    )
    (tmp_path / "app.py").write_text("print('starter')\n")
    conversation = _EditingConversation(tmp_path, writes_per_run)
    emitted: list = []
    outcome = runner._run_stream_task_phases(
        conversation,
        _cfg(workspace=str(tmp_path), verify_tests="always"),
        emitted.append,
        "Fix the starter",
        None,
        None,
        float("inf"),
        None,
        [],
        check_changes=check_changes,
    )
    notices = [m.content[0].text for m in emitted]
    return outcome, conversation, notices


def test_a_run_that_changes_a_file_stays_verified_with_no_follow_up(monkeypatch, tmp_path):
    outcome, conversation, _ = _phases(monkeypatch, tmp_path, [{"app.py": "print('fixed')\n"}])

    assert outcome.verification_state == "verified"
    assert conversation.sent_messages == ["Fix the starter"]
    assert outcome.retries_used == 0


def test_no_change_gets_one_follow_up_and_a_change_then_verifies(monkeypatch, tmp_path):
    outcome, conversation, notices = _phases(
        monkeypatch, tmp_path, [{}, {"app.py": "print('fixed')\n"}]
    )

    assert outcome.verification_state == "verified"
    assert conversation.run_calls == 2
    follow_up = conversation.sent_messages[1]
    assert "no file in it changed during this run" in follow_up
    assert str(tmp_path) in follow_up
    assert any("the agent changed no file in the project folder" in n for n in notices)
    assert outcome.retries_used == 1


def test_still_no_change_after_the_follow_up_is_unchanged(monkeypatch, tmp_path):
    outcome, conversation, notices = _phases(monkeypatch, tmp_path, [{}, {}])

    assert outcome.verification_state == "unchanged"
    assert outcome.success is False
    assert conversation.run_calls == 2
    assert outcome.retries_used == 1
    assert any(
        "changed no file in the project folder, even after Certo asked once" in note
        for note in outcome.completion_contract.limitations
    )
    assert any("reported as unchanged, not verified" in n for n in notices)


def test_certos_own_files_are_not_a_change(monkeypatch, tmp_path):
    outcome, _, _ = _phases(
        monkeypatch, tmp_path, [{"MODEL_DECISIONS.md": "x"}, {"MODEL_DECISIONS.md": "y"}]
    )
    assert outcome.verification_state == "unchanged"


def test_a_resumed_run_is_never_unchanged(monkeypatch, tmp_path):
    outcome, conversation, _ = _phases(monkeypatch, tmp_path, [{}], check_changes=False)

    assert outcome.verification_state == "verified"
    assert conversation.run_calls == 1


def _phases_out_of_time(monkeypatch, tmp_path, writes):
    """`_phases`, but the time budget is already spent when the run ends."""
    monkeypatch.setattr(runner, "_agent_changed_files", _REAL_AGENT_CHANGED_FILES)
    monkeypatch.setattr(
        runner, "_run_verification", lambda _dir, *_a: _run(_check(summary="3 passed"))
    )
    (tmp_path / "app.py").write_text("print('starter')\n")
    conversation = _EditingConversation(tmp_path, [writes])
    looks = iter(["", *(["budget_exhausted"] * 10)])
    # The run starts in time; every later look at the budget finds it spent.
    monkeypatch.setattr(runner, "_budget_spent", lambda *_a: next(looks))
    emitted: list = []
    outcome = runner._run_stream_task_phases(
        conversation,
        _cfg(workspace=str(tmp_path), verify_tests="always"),
        emitted.append,
        "Fix the starter",
        None,
        None,
        float("inf"),
        None,
        [],
        check_changes=True,
    )
    return outcome, conversation, [m.content[0].text for m in emitted]


def test_out_of_time_with_no_change_stays_budget_exhausted_with_no_follow_up(monkeypatch, tmp_path):
    # Found by the 0.1.27 local milestone benchmark: Certo said "the work
    # is verified", then asked the agent once with no time left.
    outcome, conversation, notices = _phases_out_of_time(monkeypatch, tmp_path, {})

    assert outcome.verification_state == "budget_exhausted"
    assert len(outcome.checks) == 1
    assert conversation.sent_messages == ["Fix the starter"]
    assert not any("so the work is verified" in n for n in notices)
    assert not any("Asking it once" in n for n in notices)
    assert any("changed no file" in n and "stays budget_exhausted" in n for n in notices)


def test_out_of_time_with_a_change_is_still_verified(monkeypatch, tmp_path):
    outcome, _, notices = _phases_out_of_time(monkeypatch, tmp_path, {"app.py": "print('fixed')\n"})

    assert outcome.verification_state == "verified"
    assert any("so the work is verified" in n for n in notices)


def test_only_a_verified_run_is_checked_for_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_agent_changed_files", _REAL_AGENT_CHANGED_FILES)
    monkeypatch.setattr(runner, "_run_verification", lambda _dir, *_a: _run())
    conversation = _EditingConversation(tmp_path, [{}])
    outcome = runner._run_stream_task_phases(
        conversation,
        _cfg(workspace=str(tmp_path), verify_tests="always"),
        lambda _m: None,
        "Explain the code",
        None,
        None,
        float("inf"),
        None,
        [],
    )
    assert outcome.verification_state == "inconclusive"
    assert conversation.run_calls == 1


# --- a verified run that changed the files its checks rely on ----------------


def test_a_weakened_test_is_reported_and_the_verdict_stays(monkeypatch, tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_a():\n    assert run() == 2\n    assert run(1) == 3\n"
    )
    outcome, _, _ = _phases(
        monkeypatch,
        tmp_path,
        [{"app.py": "print('fixed')\n", "tests/test_app.py": "def test_a():\n    pass\n"}],
    )

    assert outcome.verification_state == "verified"
    assert [c.path for c in outcome.check_file_changes] == [os.path.join("tests", "test_app.py")]
    note = outcome.completion_contract.limitations[-1]
    assert "The agent changed 1 file the checks rely on" in note
    assert "(1 line changed, 1 line removed)" in note


def test_new_tests_alone_are_not_reported(monkeypatch, tmp_path):
    (tmp_path / "tests").mkdir()
    outcome, _, _ = _phases(
        monkeypatch,
        tmp_path,
        [{"app.py": "print('fixed')\n", "tests/test_app.py": "def test_a():\n    pass\n"}],
    )

    assert outcome.verification_state == "verified"
    assert outcome.check_file_changes == ()
    assert not any("checks rely on" in n for n in outcome.completion_contract.limitations)


def test_stream_task_turns_off_the_change_check_only_on_resume(monkeypatch, tmp_path):
    seen: list = []

    def fake_phases(conversation, cfg, emit, task, *args, check_changes=True):
        seen.append(check_changes)
        return _verified_outcome()

    from certo.project_state import load_record

    _stub_for_state_tests(monkeypatch)
    monkeypatch.setattr(runner, "_run_stream_task_phases", fake_phases)
    runner.stream_task("do the thing", cfg=_cfg(workspace=str(tmp_path)), save_state=True)
    first = load_record(str(tmp_path))
    runner.stream_task(first.task, cfg=_cfg(workspace=str(tmp_path)), resume_from=first)
    assert seen == [True, False]


def _pty_reader_records(exc: Exception) -> list[logging.LogRecord]:
    """What the SDK terminal's logger lets through when its reader thread
    logs `exc` the way the SDK does."""
    import certo.runner  # noqa: F401 - installs the filter

    sdk_logger = logging.getLogger("openhands.tools.terminal.terminal.subprocess_terminal")
    seen: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record):
            seen.append(record)

    handler = _Keep()
    sdk_logger.addHandler(handler)
    try:
        try:
            raise exc
        except Exception as e:
            sdk_logger.error(f"PTY reader thread error: {e}", exc_info=True)  # noqa: G201 - as the SDK logs it
    finally:
        sdk_logger.removeHandler(handler)
    return seen


def test_closed_terminal_read_error_is_not_logged():
    assert _pty_reader_records(OSError(errno.EBADF, "Bad file descriptor")) == []


def test_other_terminal_reader_errors_still_log():
    assert len(_pty_reader_records(OSError(errno.EIO, "Input/output error"))) == 1
    assert len(_pty_reader_records(ValueError("boom"))) == 1


def test_run_task_passes_certo_notices_on_as_they_happen(monkeypatch):
    from openhands.sdk import Message, TextContent

    def fake_stream_task(task, *, on_message, **_kwargs):
        runner._emit_notice(on_message, "Certo: escalating from a to b")
        on_message(Message(role="assistant", content=[TextContent(text="agent text")]))
        return "outcome"

    monkeypatch.setattr(runner, "stream_task", fake_stream_task)
    notices: list[str] = []

    result = runner.run_task("do it", on_notice=notices.append)

    assert notices == ["Certo: escalating from a to b"]  # the agent's text is not a notice
    assert len(result) == 2


# --- CERTO_INDEPENDENT_TESTS: written before the build, run after ---------


def _independent_tests_run(
    monkeypatch, tmp_path, *, verdict="verified", set_results=(), **cfg_overrides
):
    """stream_task with a fake conversation, verification, writers and test
    runs (one set unless `independent_tests_sets` says otherwise; each set's
    result from `set_results`); returns (outcome, the order things happened
    in, what the fakes saw)."""
    from pathlib import Path

    import certo.independent_tests as it
    from certo.independent_tests import IndependentTestsResult, WrittenTests

    events: list[str] = []
    seen: dict = {}
    conversation = _FakeConversation(statuses_after_run=[ConversationExecutionStatus.FINISHED])
    original_run = conversation.run

    def run() -> None:
        events.append("build")
        original_run()

    conversation.run = run
    monkeypatch.setattr(runner, "Conversation", lambda **_kwargs: conversation)
    monkeypatch.setattr(runner, "build_agent", lambda cfg, **_kw: "fake-agent")
    monkeypatch.setattr(runner, "build_workspace", lambda cfg: nullcontext("fake-workspace"))
    _mock_task_tracker_and_verify(monkeypatch, verification_state=verdict)

    def fake_write(task, writer_cfg, scratch, *, project, usage_id, run_writer):
        events.append("write")
        seen.update(task=task, model=writer_cfg.model, project=project)
        seen.setdefault("scratches", []).append(scratch)
        folder = Path(scratch) / "new_tests"
        folder.mkdir(parents=True)
        return WrittenTests(
            folder=folder,
            model=writer_cfg.model,
            files=("test_x.py",),
            language="python",
            metrics={usage_id: {"accumulated_cost": 0.25}},
        )

    def fake_run(written, workspace, runner=None):
        events.append("independent tests")
        seen["ran_in"] = workspace
        return (
            results.pop(0)
            if results
            else IndependentTestsResult("failed", "1 failed, 2 passed", written.model)
        )

    results = list(set_results)
    monkeypatch.setattr(it, "write_tests", fake_write)
    monkeypatch.setattr(it, "run_independent_tests", fake_run)
    cfg_overrides.setdefault("independent_tests_sets", 1)
    cfg = _cfg(workspace=str(tmp_path), **cfg_overrides)
    outcome = runner.stream_task("Write calc.add.", cfg=cfg)
    return outcome, events, seen


def test_independent_tests_are_off_by_default(monkeypatch, tmp_path):
    outcome, events, _ = _independent_tests_run(monkeypatch, tmp_path)

    assert events == ["build"]
    assert outcome.independent_tests is None


def test_independent_tests_are_written_before_the_build_and_run_after(monkeypatch, tmp_path):
    outcome, events, seen = _independent_tests_run(monkeypatch, tmp_path, independent_tests=True)

    assert events == ["write", "build", "independent tests"]
    assert seen["task"] == "Write calc.add." and seen["model"] == "openai/gpt-4o"
    assert str(seen["project"]) == str(tmp_path) and seen["ran_in"] == str(tmp_path)
    (scratch,) = seen["scratches"]
    assert not str(scratch).startswith(str(tmp_path))  # outside the project
    assert not scratch.exists()  # removed afterwards


def test_independent_tests_never_change_the_verdict(monkeypatch, tmp_path):
    outcome, _, _ = _independent_tests_run(monkeypatch, tmp_path, independent_tests=True)

    assert outcome.verification_state == "verified"
    assert outcome.independent_tests.status == "failed"
    assert outcome.independent_tests.summary == "1 failed, 2 passed"


def test_the_writers_cost_is_in_the_run_summary(monkeypatch, tmp_path):
    outcome, _, _ = _independent_tests_run(monkeypatch, tmp_path, independent_tests=True)

    assert outcome.run_summary.total_cost == pytest.approx(0.25)


def test_independent_tests_are_skipped_under_docker(monkeypatch, tmp_path):
    notices = []
    cfg = _cfg(workspace=str(tmp_path), independent_tests=True, execution="docker")
    monkeypatch.setattr(runner, "write_test_sets", lambda *a, **k: pytest.fail("written"))
    monkeypatch.setattr(runner, "_emit_notice", lambda _emit, text: notices.append(text))

    assert runner._write_independent_tests("t", cfg, cfg, lambda _m: None) is None
    assert notices == ["Certo: independent tests are for local runs only; skipped."]


def test_independent_tests_are_skipped_on_resume(monkeypatch, tmp_path):
    notices = []
    cfg = _cfg(workspace=str(tmp_path), independent_tests=True)
    monkeypatch.setattr(runner, "write_test_sets", lambda *a, **k: pytest.fail("written"))
    monkeypatch.setattr(runner, "_emit_notice", lambda _emit, text: notices.append(text))

    assert runner._write_independent_tests("t", cfg, cfg, lambda _m: None, resuming=True) is None
    assert "aren't written on --resume" in notices[0]


def _test_sets(tmp_path, count):
    from certo.independent_tests import TestSets, WrittenTests

    scratch = tmp_path / "scratch"
    sets = []
    for k in range(1, count + 1):
        folder = scratch / f"set{k}" / "new_tests"
        folder.mkdir(parents=True)
        (folder / "test_x.py").write_text("def test_x():\n    assert True\n")
        sets.append(WrittenTests(folder=folder, model="m", files=("test_x.py",), language="python"))
    return TestSets(scratch=scratch, sets=tuple(sets))


def _kept(monkeypatch, tmp_path, count):
    import certo.independent_tests as it

    written = _test_sets(tmp_path, count)
    monkeypatch.setattr(
        it,
        "run_independent_tests",
        lambda w, ws, r=None: it.IndependentTestsResult("passed", "1 passed", "m"),
    )
    outcome = runner.TaskOutcome(
        verification_state="verified",
        completion_contract=runner.CompletionContract(
            goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
        ),
    )
    records = tmp_path / "records" / "run-1"
    result = runner._apply_independent_tests(
        outcome, written, _cfg(workspace=str(tmp_path / "project")), str(records)
    )
    return result, records / "independent_tests", written.scratch


def test_independent_tests_are_kept_in_the_run_records_not_the_project(monkeypatch, tmp_path):
    result, kept, scratch = _kept(monkeypatch, tmp_path, 1)

    assert result.independent_tests.status == "passed"
    assert (kept / "test_x.py").is_file()
    assert not scratch.exists()


def test_several_sets_are_kept_one_folder_each(monkeypatch, tmp_path):
    result, kept, scratch = _kept(monkeypatch, tmp_path, 3)

    assert result.independent_tests.summary == "3 of 3 sets passed"
    assert [p.name for p in sorted(kept.iterdir())] == ["set1", "set2", "set3"]
    assert not scratch.exists()


def test_three_sets_are_written_and_vote(monkeypatch, tmp_path):
    from certo.independent_tests import IndependentTestsResult as R

    outcome, events, seen = _independent_tests_run(
        monkeypatch,
        tmp_path,
        independent_tests=True,
        independent_tests_sets=3,
        set_results=[
            R("failed", "1 failed", "m"),
            R("passed", "4 passed", "m"),
            R("failed", "2 failed", "m"),
        ],
    )

    assert events.count("write") == 3 and events[3:] == ["build"] + ["independent tests"] * 3
    assert len({s.parent for s in seen["scratches"]}) == 1  # one scratch folder
    assert outcome.independent_tests.status == "failed"
    assert outcome.independent_tests.summary == "2 of 3 sets failed"
    assert outcome.verification_state == "verified"  # report only
    assert outcome.run_summary.total_cost == pytest.approx(0.75)  # every writer counted


def test_strict_independent_tests_turn_verified_into_independent_failed(monkeypatch, tmp_path):
    outcome, _, _ = _independent_tests_run(
        monkeypatch, tmp_path, independent_tests=True, independent_tests_strict=True
    )

    assert outcome.verification_state == "independent_failed"
    assert outcome.independent_tests.status == "failed"
    assert not outcome.success


@pytest.mark.parametrize("status", ["passed", "split", "none", "error"])
def test_strict_independent_tests_keep_verified_unless_they_failed(monkeypatch, tmp_path, status):
    from certo.independent_tests import IndependentTestsResult as R

    outcome, _, _ = _independent_tests_run(
        monkeypatch,
        tmp_path,
        independent_tests=True,
        independent_tests_strict=True,
        set_results=[R(status, "summary", "m")],
    )

    assert outcome.verification_state == "verified"


def test_strict_independent_tests_leave_other_verdicts_alone(monkeypatch, tmp_path):
    outcome, _, _ = _independent_tests_run(
        monkeypatch,
        tmp_path,
        verdict="inconclusive",
        independent_tests=True,
        independent_tests_strict=True,
    )

    assert outcome.verification_state == "inconclusive"
    assert outcome.independent_tests.status == "failed"
