"""run_progress.py: the progress line a terminal run prints. No LLM: the
conversation is a stand-in with a running cost."""

from __future__ import annotations

import threading
import types

from certo import run_progress
from certo.run_progress import (
    RunProgress,
    attach_progress,
    checks_ran,
    checks_text,
    fix_attempt,
    report_progress,
)
from certo.verification import CheckOutcome, VerificationRun


class _Conversation:
    """Has what conversation_cost reads: the models' accumulated cost."""

    def __init__(self, cost: float = 0.0) -> None:
        self.metrics = types.SimpleNamespace(accumulated_cost=cost)
        self.conversation_stats = types.SimpleNamespace(usage_to_metrics={"m": self.metrics})


def _check(name="pytest", status="passed", summary=""):
    return CheckOutcome(
        name=name,
        command=name,
        primary=True,
        status=status,
        exit_code=0 if status == "passed" else 1,
        project_root="/p",
        summary=summary,
        output="",
    )


def _progress(lines, every=120.0, **kwargs):
    progress = RunProgress(say=lines.append, every_seconds=every, **kwargs)
    progress.started -= 372  # 6m 12s ago
    return progress


def test_the_line_says_where_the_run_is_its_time_and_its_cost():
    progress = _progress([], where="milestone 2 of 4", cost_before=0.01)
    progress.model, progress.fix = "haiku", "fix attempt 1 of 2"
    progress.checks = "checks failed: pytest (2 failed)"

    assert progress.line(0.021) == (
        "Progress: milestone 2 of 4 · haiku · fix attempt 1 of 2 · "
        "checks failed: pytest (2 failed) · 6m 12s · $0.0310"
    )
    assert _progress([]).line(0).startswith("Progress: 6m 1")


def test_checks_name_only_what_failed_or_timed_out():
    passed = VerificationRun(checks=[_check(), _check("ruff")])
    failed = VerificationRun(
        checks=[
            _check(status="failed", summary="2 failed"),
            _check("ruff"),
            _check("tsc", "timed_out"),
        ]
    )

    assert checks_text(passed) == "checks verified"
    assert checks_text(failed) == "checks failed: pytest (2 failed), tsc"


def test_a_check_run_and_a_fix_attempt_each_print_a_line_with_the_cost_since_attached():
    lines: list[str] = []
    conversation = _Conversation(cost=0.5)  # spent before Certo attached the line
    attach_progress(conversation, _progress(lines), spent_before=0.002)
    conversation.metrics.accumulated_cost = 0.51

    checks_ran(conversation, VerificationRun(checks=[_check(status="failed", summary="1 failed")]))
    fix_attempt(conversation, 1, 2)

    assert lines == [
        "Progress: checks failed: pytest (1 failed) · 6m 12s · $0.0120",
        "Progress: fix attempt 1 of 2 · checks failed: pytest (1 failed) · 6m 12s · $0.0120",
    ]


def test_a_new_conversation_starts_with_no_fix_attempt_and_names_its_rung():
    lines: list[str] = []
    progress = _progress(lines)
    first = _Conversation()
    attach_progress(first, progress)
    fix_attempt(first, 1, 2)

    second = _Conversation()
    attach_progress(second, progress, model="sonnet")
    checks_ran(second, VerificationRun(checks=[_check()]))

    assert lines[-1] == "Progress: sonnet · checks verified · 6m 12s · $0.0000"


def test_nothing_is_printed_for_a_conversation_without_the_line():
    conversation = _Conversation()

    checks_ran(conversation, VerificationRun(checks=[_check()]))
    fix_attempt(conversation, 1, 2)
    attach_progress(conversation, None)
    with report_progress(conversation):
        pass

    assert conversation not in run_progress._attached


def test_while_the_agent_works_the_line_comes_every_few_seconds_and_stops_after():
    lines: list[str] = []
    printed = threading.Event()

    def say(line: str) -> None:
        lines.append(line)
        printed.set()

    conversation = _Conversation()
    attach_progress(conversation, RunProgress(say=say, every_seconds=0.01))

    with report_progress(conversation):
        assert printed.wait(5)
    count = len(lines)
    threading.Event().wait(0.05)

    assert count >= 1
    assert len(lines) == count  # the watcher stopped with the block


def test_a_line_that_cant_be_printed_never_breaks_the_run():
    def say(_line: str) -> None:
        raise BrokenPipeError

    conversation = _Conversation()
    attach_progress(conversation, RunProgress(say=say, every_seconds=0.01))

    with report_progress(conversation):
        threading.Event().wait(0.05)
