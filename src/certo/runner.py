"""Runs a task end to end and returns/streams the conversation's messages.

Result is captured via an event callback — there is no `conversation.result`.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openhands.sdk import (
    Conversation,
    ConversationExecutionStatus,
    Event,
    LLMConvertibleEvent,
    Message,
    TextContent,
)
from openhands.sdk.conversation import ConversationState
from openhands.sdk.conversation.exceptions import ConversationRunError
from openhands.sdk.event import ActionEvent, Condensation, MessageEvent, ObservationEvent
from openhands.sdk.event.conversation_error import ConversationErrorEvent
from openhands.sdk.llm.exceptions.types import LLMError
from openhands.sdk.security.confirmation_policy import AlwaysConfirm
from openhands.tools.task_tracker import TaskTrackerTool

from . import context_window
from .acceptance import AcceptanceCheck, AcceptanceCheckResult, evaluate_acceptance_checks
from .agent import build_agent
from .artifacts import resolve_run_artifacts_dir, write_run_artifacts
from .catalog_check import load_checked_catalog
from .check_files import (
    CheckFileChange,
    changes_note,
    check_file_changes,
    snapshot_check_files,
)
from .config import Config, load_config, override_llm
from .console import quiet_sdk_logs, visualizer_for
from .checkpoints import (
    Checkpoint,
    CheckpointError,
    list_checkpoints,
    rollback,
    safe_snapshot,
)
from .cost_limit import cost_limit, cost_limit_reached, pause_at_cost_limit, set_cost_limit
from .deadline import stop_at_deadline
from .independent_tests import (
    IndependentTestsResult,
    TestSets,
    run_test_sets,
    write_test_sets,
)
from .verification import (
    CheckOutcome,
    CompletionContract,
    _build_completion_contract,
    VerificationRun,
    detect_project,
    run_full_verification,
)
from .escalation import (
    FileChanges,
    ResolvedLadder,
    Rung,
    RungResult,
    climb_line,
    describe_ladder,
    failure_reason,
    handoff_message,
    load_ladder,
    rung_dicts,
    workspace_listing,
)
from .model_catalog import (
    ModelCatalog,
    classify_task,
    find_trigger,
    rank_for_profile,
    task_title,
)
from .model_pricing import estimate_run_cost, is_local
from .model_selection import (
    ModelChain,
    ModelDecisionRecord,
    OnModelChoice,
    config_for_entry,
    llm_for_entry,
    write_model_decisions,
)
from .project_env import (
    CommandRunner,
    LocalRunner,
    ProjectEnv,
    WorkspaceRunner,
    ensure_project_env,
    terminal_env,
    wants_python_env,
)
from .project_state import (
    RunRecord,
    checks_from_outcomes,
    conversations_dir,
    drop_other_conversations,
    ensure_state_dir,
    has_saved_conversation,
    now,
    resume_message,
    save_record,
)
from .run_summary import RunSummary, summarize_run
from .text_tool_calls import REMINDER as TOOL_CALL_REMINDER
from .text_tool_calls import looks_like_tool_call
from .workspace import build_workspace

logger = logging.getLogger(__name__)


class _ClosedTerminalReadFilter(logging.Filter):
    """Drops the SDK's "PTY reader thread error: [Errno 9] Bad file
    descriptor". Closing a terminal closes its file descriptor while the
    reader thread may still be waiting on it; the thread then logs that
    error, with a traceback, although nothing went wrong. It shows at the
    end of `certo bench`, where users read it as a crash. Any other reader
    error still logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith("PTY reader thread error"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        return not (isinstance(exc, OSError) and exc.errno == errno.EBADF)


logging.getLogger("openhands.tools.terminal.terminal.subprocess_terminal").addFilter(
    _ClosedTerminalReadFilter()
)

# The twelve terminal states a task run can end in. Exactly these because
# they're the ones a caller needs to tell apart to know whether to trust a
# "done" claim: real, confirmed success; no evidence either way; checks that
# pass but say nothing about the task, because the agent changed no file
# even after being asked once (see `_require_a_change`); a confirmed
# problem that automated retries couldn't fix; a fix attempt that produced
# no observable change at all (see `_failure_signature` below — a distinct
# problem from "still failing differently"); a check that kept exceeding its
# timeout even after retries (a distinct failure mode from a genuine failure
# — usually a hang/infinite loop, not a wrong answer); the agent's own
# task_tracker list still showing unfinished work after automated follow-up
# (see `_enforce_task_tracker_completion` — distinct from every check above
# since it's caught before project verification even runs); an action that
# needed CERTO_CONFIRM_MODE=always approval with no handler available to
# answer it (see `_run_with_confirmation` — caught before task_tracker or
# project verification, same reasoning as `incomplete`); the shared,
# task-level wall-clock budget (`CERTO_MAX_TASK_SECONDS`) running out
# across the initial run and every retry phase combined — distinct from a
# single `conversation.run()` call hitting its own `max_iteration_per_run`
# (which resets on every call and so cannot bound a whole task on its own,
# see DECISIONS.md); a caller-supplied, machine-checkable
# acceptance criterion (see `acceptance.py`) that was marked `required` and
# failed, downgrading what would otherwise have been `verified` — the only
# state a caller opts into by supplying `acceptance_checks` at all; and a
# run that never reached a coherent finish at all. "failed" itself is never
# a *final* value here — it's the transient signal inside the retry loop
# between "a check just failed" and "was it fixed, or did retries run out"
# (see `_verify_and_report`); it's listed because `VerificationRun.state`
# (verification.py) uses the same vocabulary and a caller may inspect a
# `TaskOutcome.checks` mid-analysis. See MANUAL.md "Test verification" and
# DECISIONS.md.
VERIFICATION_STATES = (
    "verified",
    "failed",
    "inconclusive",
    "unchanged",
    "retry_exhausted",
    "no_progress",
    "timed_out",
    "incomplete",
    "confirmation_required",
    "budget_exhausted",
    "cost_exhausted",
    "acceptance_failed",
    "independent_failed",
    "stuck",
)

# Final verdicts that prove nothing either way: not a failure, but not
# `verified` either. `--require-verification` (CLI) and
# `require_verification` (server) make them count as a failure.
UNPROVEN_STATES = ("inconclusive", "unchanged")

# VerificationRun states that mean "something needs fixing, worth retrying" —
# as opposed to "inconclusive" (nothing to retry toward) or "verified".
_RETRIABLE_STATES = ("failed", "timed_out")

# execution_status values that mean the conversation did not end via a normal
# finish — retrying or verifying against whatever state the workspace is in
# would be building on top of a run the agent itself never completed coherently.
_ABORTED_STATUSES = (ConversationExecutionStatus.STUCK, ConversationExecutionStatus.ERROR)


def _hit_step_limit(conversation: Conversation) -> bool:
    """Whether the run ended in ERROR only because the agent used all its
    steps (`CERTO_MAX_ITERATIONS`): the SDK then emits a
    `ConversationErrorEvent` with code "MaxIterationsReached" and returns
    normally (v1.47.0). Nothing broke, so the work is checked like a run
    that finished, instead of ending `stuck` unchecked. Seen live
    2026-10-19: claude-haiku-5-5's 50th step ran 116 passing tests, and the
    run still ended `stuck`. Any other error, or an event log that can't be
    read (Docker), keeps the old `stuck`."""
    try:
        if conversation.state.execution_status != ConversationExecutionStatus.ERROR:
            return False
        for event in reversed(conversation.state.events):
            if isinstance(event, ConversationErrorEvent):
                return event.code == "MaxIterationsReached"
    except Exception:  # noqa: BLE001 - unknown means "not the step limit"
        return False
    return False


# Conversations whose last run ended because a model call was cut short at
# the deadline (`_run_conversation_once`). Their ERROR status is the
# budget's doing, so `_verify_after_budget` checks their work.
_CUT_AT_DEADLINE: weakref.WeakSet[Any] = weakref.WeakSet()


def _step_limit_notice(cfg: Config) -> str:
    return (
        f"Certo: the agent used all its {cfg.max_iterations} steps (CERTO_MAX_ITERATIONS) "
        "before finishing. Checking the work it left."
    )


# Wall-clock durations a test/build tool prints in its own summary line
# (pytest's "in 3.85s", etc.) — the one kind of noise expected to differ
# between two otherwise-identical runs. Stripped only from the *comparison*
# signature below, never from the real output shown to the agent.
_DURATION_NOISE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:s|ms|seconds?|milliseconds?)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class TaskOutcome:
    """The terminal, caller-facing verdict for one task run.

    `stream_task` always returns one of these now (previously returned
    `None`); `run_task` attaches it to its `TaskResult` list subclass as
    `.outcome`, so every existing caller that only ever used the return
    value as `list[Message]` (`messages[-1]`, `len(messages)`, `if
    messages:`, iteration) keeps working unchanged.
    """

    verification_state: str  # one of VERIFICATION_STATES
    completion_contract: CompletionContract
    checks: tuple[CheckOutcome, ...] = ()
    retries_used: int = 0
    # Only non-empty when the caller supplied acceptance_checks — see
    # _apply_acceptance_checks. Evaluated regardless of verification_state
    # (even a stuck/incomplete run's workspace is still worth checking),
    # but only a required check's failure can downgrade verification_state
    # itself (from "verified" to "acceptance_failed").
    acceptance_results: tuple[AcceptanceCheckResult, ...] = ()
    # Only non-empty when cfg.model_selection == "auto" — see
    # model_selection.py's ModelChain. The same records are also written to
    # MODEL_DECISIONS.md in the project workspace (write_model_decisions).
    model_decisions: tuple[ModelDecisionRecord, ...] = ()
    # Wall-clock time, models used, tokens, and cost for the whole task —
    # see run_summary.py. Always set by stream_task.
    run_summary: RunSummary | None = None
    # Only set by escalation (see escalation.py): one entry per rung that
    # ran, in order, and the number of the rung whose verdict this is.
    rungs: tuple[RungResult, ...] = ()
    final_rung: int | None = None
    # CERTO_INDEPENDENT_TESTS: the result of the tests written before the
    # build (independent_tests.py). Report only, unless
    # CERTO_INDEPENDENT_TESTS_STRICT turns a "verified" whose tests failed
    # into "independent_failed".
    independent_tests: IndependentTestsResult | None = None
    # A verified run's changes to the files its checks rely on
    # (check_files.py). Report only, like independent_tests.
    check_file_changes: tuple[CheckFileChange, ...] = ()
    # How many times _remind_text_tool_call sent the agent back after it
    # wrote a tool call as text (see CERTO_TOOL_CALL_REMINDERS). An
    # escalation run sums every rung's own count (RungResult below).
    tool_call_reminders: int = 0

    @property
    def success(self) -> bool:
        return self.verification_state == "verified"


class TaskResult(list):
    """`run_task`'s return value: behaves exactly like the `list[Message]`
    it has always returned, plus `.outcome` (a `TaskOutcome`) for callers
    that want the structured verdict instead of re-deriving it from message
    text.
    """

    def __init__(self, messages, outcome: TaskOutcome) -> None:
        super().__init__(messages)
        self.outcome = outcome


def _run_verification(working_dir: str, runner: CommandRunner | None = None) -> VerificationRun:
    """Run the project's full verification directly — no LLM/tool-call round
    trip. A verification-step glitch (a check hangs past its own timeout, or
    something else genuinely unexpected) must not abort an otherwise-
    successful task, so it's treated as inconclusive (no checks), not
    re-raised. `runner` is where the checks run: the host, or the Docker
    container (see `_command_runner`).
    """
    try:
        return run_full_verification(working_dir, runner)
    except Exception:  # noqa: BLE001 - a verification glitch must not abort the task
        return VerificationRun(checks=[])


def _emit_verification_notices(emit: Callable[[Message], None], run: VerificationRun) -> None:
    for notice in run.notices:
        _emit_notice(emit, f"Certo: {notice}")


def _command_runner(cfg: Config, workspace: Any) -> CommandRunner:
    """Where project commands run. Under `--execution docker` that's inside
    the container, next to the agent's own terminal: a venv only works on
    the OS that created it, so the agent and verification must share the
    container's (see DECISIONS.md)."""
    if cfg.execution == "docker":
        return WorkspaceRunner(
            workspace,
            host_root=os.path.abspath(cfg.workspace),
            # DockerWorkspace's own default, matching workspace.py's bind mount.
            exec_root=str(getattr(workspace, "working_dir", "/workspace")),
        )
    return LocalRunner()


def _prepare_agent_env(
    task: str, cfg: Config, runner: CommandRunner, emit: Callable[[Message], None]
) -> ProjectEnv | None:
    """Give a Python project (or an empty workspace whose task names Python)
    its own environment before the agent starts, so the agent's terminal
    and verification use the same one. Never fatal: a setup problem is
    reported and the agent starts without it."""
    workspace = os.path.abspath(cfg.workspace)
    if not os.path.isdir(workspace):
        return None
    try:
        detection = detect_project(workspace)
        if not wants_python_env(task, detection.language, workspace):
            return None
        root = detection.root if detection.language == "python" else workspace
        setup = ensure_project_env(root, runner, stop_at=workspace)
    except Exception as exc:  # noqa: BLE001 - setup must never abort the task
        _emit_notice(emit, f"Certo: could not prepare a project environment ({exc}).")
        return None
    for notice in setup.notices:
        _emit_notice(emit, f"Certo: {notice}")
    if setup.env is None:
        _emit_notice(
            emit,
            f"Certo: the agent starts without a project environment: {setup.unavailable_reason}",
        )
    return setup.env


def _warn_small_window(cfg: Config, emit: Callable[[Message], None]) -> None:
    """A notice when the model's known context window is under
    CERTO_CONTEXT_WARN_TOKENS (context_window.py). Never fatal: a window
    that can't be learned gives no notice."""
    if not cfg.context_warn_tokens:
        return
    try:
        tokens = context_window.known_context_tokens(
            cfg.model, cfg.llm_context_tokens, cfg.base_url, cfg.llm_timeout_seconds or 600
        )
    except Exception:  # noqa: BLE001 - a warning must never stop the run
        return
    if tokens and tokens < cfg.context_warn_tokens:
        message = context_window.small_window_warning(
            cfg.model, tokens, cfg.context_warn_tokens, bool(cfg.llm_context_tokens), cfg.condense
        )
        _emit_notice(emit, f"Certo: {message}")


def _is_clean_no_tests_collected(run: VerificationRun) -> bool:
    """True only for the specific, well-defined "pytest ran cleanly and
    collected zero tests" signal — the one case req'd to keep this feature's
    original silent, non-blocking behavior (see MANUAL.md "Test
    verification"). Any other inconclusive outcome (npm missing, a
    configured lint/typecheck tool not installed, an unknown project type,
    ...) is a genuine "we don't know" and must be visible, not silently
    swept in with this one.
    """
    return (
        len(run.checks) == 1
        and run.checks[0].name == "pytest"
        and run.checks[0].status == "skipped"
    )


def _failure_signature(run: VerificationRun) -> tuple:
    """A signature of a `VerificationRun`'s failing/timed-out checks, stable
    across cosmetic differences (wall-clock timing) but sensitive to any
    real change in what actually failed.

    Used to catch a distinct problem from "still failing": a fix attempt
    that provably changed *nothing observable* — the exact same check,
    same exit code, same output — even though a real code edit and a real
    verification run happened in between. Confirmed live: an agent edited
    `move_disk`'s comparison operator (`<=` to `<`) twice across two retries
    to "fix" a failing test, but the edit was a no-op for that failure (the
    code path the test actually exercised was gated by a different branch
    entirely) — pytest's output was identical, digit-for-digit, before and
    after both edits except for its own run-duration footer. Two identical
    fix-then-still-broken cycles in a row is a much stronger, cheaper, and
    more reliable signal to stop on than trying to judge whether the
    agent's own prose explanation still makes sense (see DECISIONS.md
    for why a text-coherence heuristic was rejected in favor
    of this one).
    """
    problems = run.failing + run.timed_out_checks
    return tuple(
        (c.name, c.status, c.exit_code, _DURATION_NOISE_RE.sub("", c.output)) for c in problems
    )


# If a collection-time error is a syntax/indentation problem, the fix is
# almost always a one- or two-line structural correction at an exact
# location pytest's own traceback already names — not a reason to rewrite
# the file. Confirmed live this needed saying explicitly: across repeated
# verification retries, the agent kept doing full-file rewrites to "fix" an
# IndentationError, each one leaving a new orphaned fragment (a stray
# top-level `return` between two methods) that produced a *different*
# IndentationError on the next check — file size grew, the bug moved, it
# never got fixed. Only fires for this specific error class; a logic-level
# test failure doesn't get this nudge since a broader edit may genuinely be
# the right fix there.
_SYNTAX_ERROR_MARKERS = ("IndentationError", "SyntaxError", "TabError")

# The JS/TS analogue of _SYNTAX_ERROR_MARKERS above, for an `npm run build`
# (or `npm test`) failure — confirmed live against the actual error class
# this generalization was built for: a Vite/oxc parse error ("Adjacent JSX
# elements must be wrapped in an enclosing tag") from unclosed/sibling JSX
# in App.tsx.
_JS_SYNTAX_ERROR_MARKERS = ("PARSE_ERROR", "SyntaxError", "Unexpected token")


def _check_followup(check: CheckOutcome) -> str:
    if check.status == "timed_out":
        guidance = (
            "This check exceeded its timeout and was killed — most likely "
            "an infinite loop, an unbounded wait, or a hang in the code you "
            "wrote, not a slow environment. Find and fix whatever is "
            "hanging; do not simply increase a timeout value (if one "
            "exists) as a substitute for fixing the actual cause."
        )
        return f"### {check.name} (`{check.command}`) — {check.summary}\n\n{check.output}\n\n{guidance}"
    guidance = (
        "Fix the underlying issue yourself — do not weaken, skip, delete, or "
        "disable this check to make it pass — and only stop once it "
        "actually succeeds. Make a minimal, targeted edit at the exact "
        "location the output points to rather than rewriting the whole file "
        "from scratch — a full rewrite risks losing or duplicating code you "
        "already had correct and introducing a new bug elsewhere."
    )
    if any(marker in check.output for marker in _SYNTAX_ERROR_MARKERS):
        guidance += (
            " This specific failure is a Python syntax/indentation error, "
            "not a logic bug: open the file, view the exact line(s) the "
            "traceback names, and fix only that structural issue "
            "(indentation level, a misplaced statement, a missing block) — "
            "verify the file parses (e.g. `python -m py_compile "
            "<file>`) before moving on."
        )
    elif any(marker in check.output for marker in _JS_SYNTAX_ERROR_MARKERS):
        guidance += (
            " This is a JavaScript/TypeScript syntax or parse error: open "
            "the exact file and line the error names and fix only that "
            "structural issue (e.g. wrap adjacent JSX elements in a single "
            "enclosing tag or fragment `<>...</>`)."
        )
    return f"### {check.name} (`{check.command}`) — {check.summary}\n\n{check.output}\n\n{guidance}"


def _verification_followup(run: VerificationRun) -> str:
    problem_checks = run.failing + run.timed_out_checks
    sections = "\n\n---\n\n".join(_check_followup(c) for c in problem_checks)
    return (
        "Automated verification ran the project's checks after you "
        "finished, and the following are still failing:\n\n"
        f"{sections}\n\n"
        "Fix every issue above before finishing again — a `finish` call is "
        "not appropriate while any of them are still failing or hanging."
    )


# The `name` of every message Certo itself writes (never the agent's), so a
# caller can show Certo's notices as they happen (cli.py's on_notice).
NOTICE_NAME = "certo"


def _emit_notice(emit: Callable[[Message], None], text: str) -> None:
    emit(Message(role="assistant", content=[TextContent(text=text)], name=NOTICE_NAME))


def is_notice(message: Message) -> bool:
    """True for a message Certo wrote (`_emit_notice`), not the agent."""
    return getattr(message, "name", None) == NOTICE_NAME


# A caller-supplied decision function for CERTO_CONFIRM_MODE=always:
# given the agent's pending (not-yet-executed) actions, return True to
# approve them and let the run continue, False to reject them. `cli.py`
# supplies a real terminal-prompting implementation; server.py supplies
# none (no terminal to prompt at) — see `_run_with_confirmation` for what
# happens when no callback is given.
ConfirmCallback = Callable[[Sequence[ActionEvent]], bool]

# A caller-supplied handler for CERTO_INTERACTIVE=yes: given the narrative
# text produced since the last checkpoint, return the human's reply (sent
# back to the agent) or a falsy value to end the interactive loop and let
# the task proceed to task_tracker/verification as usual. `cli.py` supplies
# a real terminal-prompting implementation; server.py supplies none (no
# terminal to prompt at, same reasoning as ConfirmCallback above) — see
# `stream_task`'s interactive loop for what happens when no callback is
# given (nothing: cfg.interactive alone has no effect without one).
OnAwaitingInput = Callable[[str], str | None]


def _narrative_text(messages: Sequence[Message]) -> str:
    """Join the human-readable text of every non-echo message — the same
    extraction rule as `server.py`'s `_narrative_texts`, kept as its own
    small copy here rather than imported (`server.py` depends on this
    module, not the other way around). See that function's docstring for
    why `role == "assistant"` is the wrong filter: an assistant turn that
    makes a tool call has empty `content` (the call lives in `tool_calls`);
    the actual reply/finish text arrives as a `tool`-role message instead.
    """
    texts = []
    for message in messages:
        if message.role in ("system", "user"):
            continue
        for content in message.content:
            text = getattr(content, "text", None)
            if text:
                texts.append(text)
    return "\n\n".join(texts)


_WAITING_FOR_CONFIRMATION = ConversationExecutionStatus.WAITING_FOR_CONFIRMATION


def _pending_actions(conversation: Conversation) -> list[ActionEvent]:
    return ConversationState.get_unmatched_actions(conversation.state.active_branch())


def _describe_pending_action(action_event: ActionEvent) -> str:
    if action_event.action is None:
        return action_event.tool_name
    return f"{action_event.tool_name}({action_event.action})"


def _confirmation_required_contract(task: str) -> CompletionContract:
    return CompletionContract(
        goal=task,
        acceptance_criteria=["The task described in the original request is implemented."],
        verification_checks=[],
        limitations=[
            (
                "The agent proposed an action that required confirmation "
                "(CERTO_CONFIRM_MODE=always), but no interactive approval "
                "handler was available to answer it, so the run was stopped "
                "before task_tracker or project verification could run."
            )
        ],
    )


def _budget_exhausted_contract(task: str, cfg: Config) -> CompletionContract:
    return CompletionContract(
        goal=task,
        acceptance_criteria=["The task described in the original request is implemented."],
        verification_checks=[],
        limitations=[
            (
                "The task's shared wall-clock budget "
                f"(CERTO_MAX_TASK_SECONDS={cfg.max_task_seconds}) ran out before "
                "the task reached a normal finish, so its own completion claim, if "
                "any, was not verified."
            )
        ],
    )


def _cost_exhausted_contract(task: str, cfg: Config) -> CompletionContract:
    return CompletionContract(
        goal=task,
        acceptance_criteria=["The task described in the original request is implemented."],
        verification_checks=[],
        limitations=[
            (
                f"The task's cost limit (CERTO_MAX_TASK_COST={cfg.max_task_cost:g}) was "
                "reached before the task reached a normal finish, so its own completion "
                "claim, if any, was not verified."
            )
        ],
    )


# _run_with_confirmation's outcome for one call: "ok" means the run reached
# a normal terminal status (finished, stuck, error — anything but an
# unanswered confirmation or an exhausted budget); the other two values are
# each their own terminal TaskOutcome.verification_state at the call site.
_RUN_OK = "ok"
_RUN_CONFIRMATION_REQUIRED = "confirmation_required"
_RUN_BUDGET_EXHAUSTED = "budget_exhausted"
_RUN_COST_EXHAUSTED = "cost_exhausted"


def _budget_spent(conversation: Conversation, deadline: float) -> str:
    """Which of the task's budgets is spent, as the verdict it gives:
    `budget_exhausted` (time), `cost_exhausted` (CERTO_MAX_TASK_COST), or
    "" while both last."""
    if time.monotonic() >= deadline:
        return _RUN_BUDGET_EXHAUSTED
    if cost_limit_reached(conversation):
        return _RUN_COST_EXHAUSTED
    return ""


def _exhausted_contract(state: str, task: str, cfg: Config) -> CompletionContract:
    if state == _RUN_COST_EXHAUSTED:
        return _cost_exhausted_contract(task, cfg)
    return _budget_exhausted_contract(task, cfg)


def _cost_limit_notice(conversation: Conversation, cfg: Config) -> str:
    found = cost_limit(conversation)
    spent = f"${found.spent(conversation):.4f}" if found is not None else "the cost so far"
    return (
        f"Certo: the task has cost {spent}, reaching its limit "
        f"(CERTO_MAX_TASK_COST={cfg.max_task_cost:g}). The agent was stopped."
    )


def _outcome_for_run_result(
    result: str,
    task: str,
    cfg: Config,
    *,
    checks: tuple[CheckOutcome, ...] = (),
    retries_used: int = 0,
) -> TaskOutcome | None:
    """Build the terminal `TaskOutcome` for a non-`"ok"` `_run_with_confirmation`
    result (`"confirmation_required"`, `"budget_exhausted"` or
    `"cost_exhausted"`), or `None` if
    `result == "ok"` — the caller's signal to proceed normally instead of
    returning early. Shared by all three call sites so each doesn't repeat
    its own contract-selection branch.
    """
    if result == _RUN_OK:
        return None
    contract = (
        _confirmation_required_contract(task)
        if result == _RUN_CONFIRMATION_REQUIRED
        else _exhausted_contract(result, task, cfg)
    )
    return TaskOutcome(
        verification_state=result,
        completion_contract=contract,
        checks=checks,
        retries_used=retries_used,
    )


# Per conversation: how many tool-call reminders were sent, and the id of
# the last message reminded about (`_remind_text_tool_call`).
_TOOL_CALL_REMINDERS: weakref.WeakKeyDictionary[Any, tuple[int, str]] = weakref.WeakKeyDictionary()


def _reminders_sent(conversation: Conversation) -> int:
    """How many tool-call reminders this conversation has been sent so far."""
    return _TOOL_CALL_REMINDERS.get(conversation, (0, ""))[0]


def _remind_text_tool_call(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    deadline: float,
) -> bool:
    """When the run just ended on a tool call the model wrote as text
    (text_tool_calls.py), tell the agent to make it as a real call and
    return True, so the caller runs the conversation again. At most
    `CERTO_TOOL_CALL_REMINDERS` times per conversation, once per message,
    and never past the deadline or the cost limit. A model that makes real
    tool calls never gets here: the last message must be text that is, as
    a whole, a call to one of the agent's tools."""
    sent, last_id = _TOOL_CALL_REMINDERS.get(conversation, (0, ""))
    if sent >= cfg.tool_call_reminders:
        return False
    try:
        if conversation.state.execution_status != ConversationExecutionStatus.FINISHED:
            return False
        event = _last_agent_event(conversation.state.events)
        if not isinstance(event, MessageEvent) or event.id == last_id:
            return False
        text = "".join(c.text for c in event.llm_message.content if isinstance(c, TextContent))
        if not looks_like_tool_call(text, _tool_parameters(conversation)):
            return False
    except Exception:  # noqa: BLE001 - an event log that can't be read (Docker) means no reminder
        return False
    if time.monotonic() >= deadline or cost_limit_reached(conversation):
        return False
    sent += 1
    _TOOL_CALL_REMINDERS[conversation] = (sent, event.id)
    _emit_notice(
        emit,
        "Certo: the agent wrote a tool call as text instead of making it, so "
        f"nothing ran. Asking it to make the call ({sent} of {cfg.tool_call_reminders}).",
    )
    conversation.send_message(TOOL_CALL_REMINDER)
    return True


def _last_agent_event(events: Sequence[Event]) -> Event | None:
    """The agent's most recent message or action."""
    for event in reversed(events):
        if isinstance(event, (MessageEvent, ActionEvent)) and event.source == "agent":
            return event
    return None


def _tool_parameters(conversation: Conversation) -> dict[str, set[str]] | None:
    """Each of the agent's tools with its parameter names, or None (then
    text_tool_calls.DEFAULT_TOOLS) when they can't be read."""
    try:
        return {
            name: set(tool.action_type.model_fields)
            for name, tool in conversation.agent.tools_map.items()
        }
    except Exception:  # noqa: BLE001 - e.g. a remote conversation's agent
        return None


def _run_conversation_once(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    model_chain: ModelChain | None,
    deadline: float = float("inf"),
) -> None:
    """One `conversation.run()` call, transparently falling back through
    `model_chain` on a provider/API-level failure (auth error, rate limit,
    provider outage, context overflow — anything LiteLLM itself raises)
    until one succeeds or the chain is exhausted, in which case the last
    such error is re-raised. Any other exception (a real bug, not a
    provider problem) always propagates immediately, whether or not auto
    model selection is active — this is not a general retry-on-any-error
    mechanism.

    `LocalConversation.run()` catches every exception its run loop raises
    and re-raises it wrapped as `ConversationRunError` (confirmed by reading
    the SDK source, not assumed) — `.original_exception` is the real
    underlying exception, checked against
    `openhands.sdk.llm.exceptions.types.LLMError` here.

    Took two rounds of live verification to land on the right type, not
    assumed either time: a first guess (`litellm.exceptions.APIError`) was
    wrong because every concrete LiteLLM exception actually subclasses the
    *same-named* class from the `openai` package, not `litellm.exceptions`'
    own base (confirmed by inspecting fully-qualified `__mro__` entries, not
    just `__name__`, which hid this at first). A second guess
    (`openai.OpenAIError`) was *also* wrong, caught only by an actual live
    call with a deliberately invalid key: the SDK wraps every LLM-call
    failure in its own `LLMError` hierarchy
    (`LLMAuthenticationError`/`LLMRateLimitError`/`LLMTimeoutError`/
    `LLMContextWindowExceedError`/`LLMServiceUnavailableError`/
    `LLMBadRequestError`/...) before it ever reaches this code —
    `exc.original_exception` was a real `LLMAuthenticationError`, not a bare
    LiteLLM/OpenAI exception at all. `LLMError` is that hierarchy's one
    common base.

    A no-op fallback (behaves exactly like a bare `conversation.run()` call)
    when `model_chain` is `None` (auto mode off) or `cfg.execution !=
    "local"` (`conversation.switch_llm` doesn't exist on `RemoteConversation`
    — see DECISIONS.md).
    """
    while True:
        try:
            # The run can't outlast `deadline` or the cost limit: see
            # deadline.py and cost_limit.py.
            with stop_at_deadline(conversation, deadline), pause_at_cost_limit(conversation):
                conversation.run()
            found = cost_limit(conversation)
            if found is not None and not found.announced and found.reached(conversation):
                found.announced = True
                _emit_notice(emit, _cost_limit_notice(conversation, cfg))
            if _remind_text_tool_call(conversation, cfg, emit, deadline):
                continue
            return
        except ConversationRunError as exc:
            if time.monotonic() >= deadline and isinstance(exc.original_exception, LLMError):
                # A model call cut short by the deadline (deadline.py caps its
                # timeout and stops its retries): the budget ran out, the
                # model didn't fail. The work so far is still checked.
                _CUT_AT_DEADLINE.add(conversation)
                return
            if (
                model_chain is None
                or cfg.execution != "local"
                or not isinstance(exc.original_exception, LLMError)
            ):
                raise
            failed_name = model_chain.current.name
            next_entry = model_chain.advance(
                kind="escalation_api_failure",
                reason=(
                    f"{failed_name} failed with "
                    f"{type(exc.original_exception).__name__}: {exc.original_exception}"
                ),
            )
            if next_entry is None:
                raise
            _emit_notice(
                emit,
                f"Certo: {failed_name} failed "
                f"({type(exc.original_exception).__name__}) — switching to "
                f"{next_entry.name} and retrying.",
            )
            conversation.switch_llm(
                llm_for_entry(cfg, next_entry, usage_id=f"certo:{next_entry.name}")
            )


def _run_with_confirmation(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    on_confirm: ConfirmCallback | None,
    deadline: float = float("inf"),
    model_chain: ModelChain | None = None,
) -> str:
    """Drive `conversation.run()` to completion, resolving every
    `AlwaysConfirm` pause along the way instead of leaving it unhandled —
    the actual wiring `CERTO_CONFIRM_MODE=always` previously lacked (it
    was parsed/validated in `config.py` but never attached to a real
    `ConfirmationPolicyBase`; see DECISIONS.md) — and enforcing the shared,
    task-level `CERTO_MAX_TASK_SECONDS` wall-clock budget before every
    single `.run()` call it makes, not just the first. A drop-in
    replacement for a bare `conversation.run()` call: when
    `cfg.confirm_mode != "always"` and the budget isn't exhausted, it just
    runs once and returns `"ok"`, identical to the old behavior.

    Returns `"ok"` if the run reached a normal terminal status.  Returns
    `"confirmation_required"` only when the conversation paused for
    confirmation and no `on_confirm` callback was available to answer it.
    Returns `"budget_exhausted"` only when `deadline` (an absolute
    `time.monotonic()` timestamp — see `stream_task`) had already passed
    before a `.run()` call was allowed to start, and `"cost_exhausted"`
    when the cost limit (cost_limit.py) had been reached. Any non-`"ok"` value
    means the caller must treat it as its own terminal outcome rather than
    proceeding to task_tracker/project verification against a run that
    never actually continued (or never started another retry). Never
    silently approves a pending action (defeats the safety gate
    `CERTO_CONFIRM_MODE=always` exists for), never silently lets a run
    keep going past its budget, and never loops forever with nobody able
    to answer a confirmation.

    `deadline` closes a real gap: each resumed `.run()` call gets its own
    fresh `max_iteration_per_run` budget from the SDK — confirmed by
    reading `local_conversation.py`: `iteration` is a local variable reset
    to `0` at the top of every `run()` call, not persisted across calls —
    so `CERTO_MAX_ITERATIONS` alone cannot bound how long one task runs
    in total across the initial run and every retry phase combined (see
    DECISIONS.md for the exact multiplication and why a
    wall-clock budget was chosen over reverse-engineering the SDK's
    internal per-call iteration count). Checking it before *every* `.run()`
    call this function makes — including each confirm/reject round-trip —
    means a long approve/reject back-and-forth can't exceed it either.
    """
    spent = _budget_spent(conversation, deadline)
    if spent:
        return spent
    _run_conversation_once(conversation, cfg, emit, model_chain, deadline)
    if cfg.confirm_mode != "always":
        return _RUN_OK
    while conversation.state.execution_status == _WAITING_FOR_CONFIRMATION:
        pending = _pending_actions(conversation)
        if on_confirm is None:
            summary = "; ".join(_describe_pending_action(a) for a in pending)
            _emit_notice(
                emit,
                "Certo confirm-mode: the agent proposed an action that "
                f"needs approval ({summary}), but no interactive approval "
                "handler is available in this context. Stopping rather "
                "than silently approving it or waiting on confirmations "
                "nobody can answer.",
            )
            conversation.reject_pending_actions(
                "Certo confirm-mode: no approval handler available; rejected automatically."
            )
            return _RUN_CONFIRMATION_REQUIRED
        spent = _budget_spent(conversation, deadline)
        if spent == _RUN_BUDGET_EXHAUSTED:
            _emit_notice(
                emit,
                "Certo: the task's shared wall-clock budget "
                f"(CERTO_MAX_TASK_SECONDS={cfg.max_task_seconds}) ran out while "
                "waiting on a confirm-mode approval. Stopping.",
            )
        if spent:
            return spent
        if on_confirm(pending):
            _run_conversation_once(conversation, cfg, emit, model_chain, deadline)
        else:
            conversation.reject_pending_actions("Rejected by the user via Certo confirm-mode.")
            _run_conversation_once(conversation, cfg, emit, model_chain, deadline)
    return _RUN_OK


def _verify_after_budget(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    task: str,
    runner: CommandRunner | None,
    on_verification: Callable[[VerificationRun], None] | None,
    state: str = _RUN_BUDGET_EXHAUSTED,
    before: dict[str, tuple[int, int]] | None = None,
) -> TaskOutcome:
    """The time budget ran out while the agent's last run was still going
    (it is checked only between runs). The checks need no model, so they
    run once, with no fix attempt: work that passes is `verified`, anything
    else stays `budget_exhausted`, now with the check results. Found by the
    0.1.15 local benchmark: three slow runs passed the hidden tests but
    were reported `budget_exhausted` unchecked. A run that ended in an
    error, or with checks turned off, stays `budget_exhausted` as before.
    The same when the cost limit stopped the agent (`state` is then
    `cost_exhausted`): checks cost nothing. With `before` (the folder's
    listing at the start), passing checks on a folder the agent didn't
    change say nothing, so the verdict stays exhausted: there is no time
    left to ask the agent, as `_require_a_change` would."""
    exhausted = TaskOutcome(
        verification_state=state,
        completion_contract=_exhausted_contract(state, task, cfg),
    )
    status = conversation.state.execution_status
    if cfg.verify_tests != "always" or (
        status in _ABORTED_STATUSES
        and not _hit_step_limit(conversation)
        and conversation not in _CUT_AT_DEADLINE
    ):
        return exhausted
    run = _run_verification(os.path.abspath(cfg.workspace), runner)
    _emit_verification_notices(emit, run)
    if on_verification is not None:
        on_verification(run)
    if run.state != "verified":
        return replace(exhausted, checks=tuple(run.checks))
    if state == _RUN_COST_EXHAUSTED:
        budget, setting = "cost limit was reached", f"CERTO_MAX_TASK_COST={cfg.max_task_cost:g}"
    else:
        budget, setting = "time budget ran out", f"CERTO_MAX_TASK_SECONDS={cfg.max_task_seconds}"
    if before is not None and not _agent_changed_files(cfg.workspace, before):
        _emit_notice(
            emit,
            f"Certo: the {budget} ({setting}) during the agent's last step. The "
            "project's checks pass, but the agent changed no file in the project "
            f"folder, so they say nothing about this task: the verdict stays {state}.",
        )
        return replace(exhausted, checks=tuple(run.checks))
    _emit_notice(
        emit,
        f"Certo: the {budget} ({setting}) during the agent's last step, but the "
        "project's checks pass, so the work is verified.",
    )
    contract = _build_completion_contract(task, run, skipped=False, aborted=False)
    limitations = [
        *contract.limitations,
        (
            f"The {budget} before the agent finished its last step; the checks ran "
            "once afterwards, with no fix attempt."
        ),
    ]
    return TaskOutcome(
        verification_state="verified",
        completion_contract=replace(contract, limitations=limitations),
        checks=tuple(run.checks),
    )


def _verify_and_report(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    task: str,
    on_confirm: ConfirmCallback | None = None,
    deadline: float = float("inf"),
    model_chain: ModelChain | None = None,
    runner: CommandRunner | None = None,
    on_verification: Callable[[VerificationRun], None] | None = None,
    before: dict[str, tuple[int, int]] | None = None,
) -> TaskOutcome:
    """Post-hoc safety net for agent.py's `_VERIFY_BEFORE_FINISH_SUFFIX`: run
    the project's own checks ourselves instead of trusting the agent's
    self-report, and never report a failed or unverified run as success.

    Confirmed live this matters, not just in theory — see DECISIONS.md
    for two independent, concrete false-pass reproductions
    (a Python `IndentationError` the agent's own summary misdiagnosed, and a
    JSX parse error a pytest-only check couldn't even see). Bounded by
    `cfg.max_verify_retries` so a project whose checks are simply wrong, or a
    bug the model can't fix, doesn't loop forever.
    """
    spent = _budget_spent(conversation, deadline)
    if spent:
        return _verify_after_budget(
            conversation, cfg, emit, task, runner, on_verification, spent, before
        )

    status = conversation.state.execution_status
    step_limited = status in _ABORTED_STATUSES and _hit_step_limit(conversation)
    if step_limited:
        _emit_notice(emit, _step_limit_notice(cfg))
    elif status in _ABORTED_STATUSES:
        contract = _build_completion_contract(task, None, skipped=False, aborted=True)
        _emit_notice(
            emit,
            "Certo verification: the agent's run ended in a "
            f"'{status.value}' state before it reached a normal finish, so "
            "its own claims — if it made any — were not verified. This task "
            "needs manual attention.",
        )
        return TaskOutcome(verification_state="stuck", completion_contract=contract)

    if cfg.verify_tests != "always":
        contract = _build_completion_contract(task, None, skipped=True, aborted=False)
        return TaskOutcome(verification_state="inconclusive", completion_contract=contract)

    working_dir = os.path.abspath(cfg.workspace)
    attempts_left = cfg.max_verify_retries
    retries_used = 0
    run = _run_verification(working_dir, runner)
    _emit_verification_notices(emit, run)
    if on_verification is not None:
        on_verification(run)

    while run.state in _RETRIABLE_STATES:
        if attempts_left <= 0:
            contract = _build_completion_contract(task, run, skipped=False, aborted=False)
            # "retry_exhausted" for a genuine failure (real output the agent
            # could act on), but a persistent timeout is kept as its own
            # terminal state — a hang that never resolves across retries is
            # a different problem from a wrong answer, worth telling apart.
            final_state = "retry_exhausted" if run.state == "failed" else "timed_out"
            problem_text = "still failing" if run.state == "failed" else "still timing out"
            problems = "; ".join(c.summary for c in run.failing + run.timed_out_checks)
            _emit_notice(
                emit,
                f"Certo verification: the project's checks are {problem_text} "
                f"after {cfg.max_verify_retries} automated fix "
                f"attempt(s) ({problems}). Giving up — this project needs "
                "manual attention.",
            )
            return TaskOutcome(
                verification_state=final_state,
                completion_contract=contract,
                checks=tuple(run.checks),
                retries_used=retries_used,
            )
        previous_signature = _failure_signature(run)
        attempts_left -= 1
        retries_used += 1
        if model_chain is not None and cfg.execution == "local":
            failed_name = model_chain.current.name
            next_entry = model_chain.advance(
                kind="escalation_quality_failure",
                reason=f"{failed_name}'s fix attempt still failed verification ({run.state}).",
            )
            if next_entry is not None:
                _emit_notice(
                    emit,
                    f"Certo: escalating from {failed_name} to {next_entry.name} "
                    "after a failed verification retry.",
                )
                conversation.switch_llm(
                    llm_for_entry(cfg, next_entry, usage_id=f"certo:{next_entry.name}")
                )
        conversation.send_message(_verification_followup(run))
        run_result = _run_with_confirmation(
            conversation, cfg, emit, on_confirm, deadline, model_chain
        )
        outcome = _outcome_for_run_result(
            run_result, task, cfg, checks=tuple(run.checks), retries_used=retries_used
        )
        if outcome is not None:
            return outcome

        retry_status = conversation.state.execution_status
        step_limited = retry_status in _ABORTED_STATUSES and _hit_step_limit(conversation)
        if step_limited:
            _emit_notice(emit, _step_limit_notice(cfg))
        elif retry_status in _ABORTED_STATUSES:
            contract = _build_completion_contract(task, run, skipped=False, aborted=True)
            _emit_notice(
                emit,
                "Certo verification: the agent got stuck "
                f"(status '{retry_status.value}') while retrying, after "
                f"{retries_used} fix attempt(s). This task needs manual "
                "attention.",
            )
            return TaskOutcome(
                verification_state="stuck",
                completion_contract=contract,
                checks=tuple(run.checks),
                retries_used=retries_used,
            )
        run = _run_verification(working_dir, runner)
        _emit_verification_notices(emit, run)
        if on_verification is not None:
            on_verification(run)

        # A fix attempt that changes literally nothing observable is a
        # different, cheaper-to-detect problem than "still failing" — stop
        # now rather than spending the rest of the retry budget on attempts
        # unlikely to help. See `_failure_signature`'s docstring for the
        # live case this catches.
        if run.state in _RETRIABLE_STATES and _failure_signature(run) == previous_signature:
            contract = _build_completion_contract(task, run, skipped=False, aborted=False)
            problems = "; ".join(c.summary for c in run.failing + run.timed_out_checks)
            _emit_notice(
                emit,
                "Certo verification: the fix attempt just made produced "
                f"no observable change — the same check ({problems}) is "
                "still failing with identical output (ignoring timing). "
                "Stopping early rather than spending the rest of the retry "
                "budget on attempts that already provably didn't help — "
                "this project needs manual attention.",
            )
            return TaskOutcome(
                verification_state="no_progress",
                completion_contract=contract,
                checks=tuple(run.checks),
                retries_used=retries_used,
            )

    if step_limited and run.state != "verified":
        # Cut off before finishing, and the checks found nothing that shows
        # the task done: nothing to claim, as before.
        contract = _build_completion_contract(task, run, skipped=False, aborted=True)
        _emit_notice(
            emit,
            "Certo verification: the agent used all its steps before finishing, and "
            "the project's checks can't show the task is done. This task needs "
            "manual attention.",
        )
        return TaskOutcome(
            verification_state="stuck",
            completion_contract=contract,
            checks=tuple(run.checks),
            retries_used=retries_used,
        )
    contract = _build_completion_contract(task, run, skipped=False, aborted=False)
    if run.state == "inconclusive" and not _is_clean_no_tests_collected(run):
        summaries = "; ".join(c.summary for c in run.checks) or "no applicable check was found"
        _emit_notice(
            emit,
            "Certo verification: no automated check applies to this "
            f"project ({summaries}) The agent's own completion claim was not "
            "independently verified.",
        )
    return TaskOutcome(
        verification_state=run.state,
        completion_contract=contract,
        checks=tuple(run.checks),
        retries_used=retries_used,
    )


def _task_tracker_snapshot(conversation: Conversation) -> list | None:
    """Return the task_tracker tool's most recently observed task list (a
    list of TaskItem-shaped objects with `.title`/`.status`/`.notes` —
    `TaskItem` itself isn't part of `openhands.tools.task_tracker`'s public
    `__all__`, so accessed structurally here rather than imported), or
    `None` if the tool was never invoked in this conversation.

    `None` is deliberately not a violation: the tool's own description says
    trivial, single-step tasks don't need it, and `get_default_tools()`
    always includes it whether or not a given task calls for it. Confirmed
    live (not assumed) that `conversation.state.events` holds every
    `ObservationEvent` for the conversation's lifetime — including ones
    from earlier `conversation.run()` calls — and that `ObservationEvent
    .tool_name` for a task_tracker call equals `TaskTrackerTool.name`
    (`"task_tracker"`, derived from the class name, not hardcoded here in
    case a future SDK version renames it).
    """
    snapshot: list | None = None
    for event in conversation.state.events:
        if isinstance(event, ObservationEvent) and event.tool_name == TaskTrackerTool.name:
            snapshot = list(getattr(event.observation, "task_list", []))
    return snapshot


def _pending_task_items(task_list: list) -> list:
    return [item for item in task_list if item.status != "done"]


def _task_tracker_followup(pending: list) -> str:
    lines = "\n".join(
        f"- [{item.status}] {item.title}" + (f" — {item.notes}" if item.notes else "")
        for item in pending
    )
    return (
        "Certo check: your own task_tracker list still has the following "
        f"item(s) not marked done:\n\n{lines}\n\n"
        "If the task is genuinely complete, use task_tracker to mark each "
        "item done (or remove it if it no longer applies) before finishing "
        "again. If an item is truly blocked, say so explicitly in your "
        "final message and explain why — do not leave it as 'todo' or "
        "'in_progress' and declare the task finished anyway."
    )


def _task_tracker_completion_contract(task: str, pending: list) -> CompletionContract:
    pending_desc = "; ".join(f"'{item.title}' ({item.status})" for item in pending)
    return CompletionContract(
        goal=task,
        acceptance_criteria=[
            "The task described in the original request is implemented.",
            ("The agent's own task_tracker list has no items left as 'todo' or 'in_progress'."),
        ],
        verification_checks=[],
        limitations=[
            (
                "The agent's own task_tracker list still shows unfinished "
                f"item(s) after automated follow-up ({pending_desc}); project "
                "verification checks were not run, since completion was never "
                "established."
            )
        ],
    )


def _enforce_task_tracker_completion(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    task: str,
    on_confirm: ConfirmCallback | None = None,
    deadline: float = float("inf"),
    model_chain: ModelChain | None = None,
) -> TaskOutcome | None:
    """Post-hoc safety net for `_AUTONOMOUS_SUFFIX`'s "never leave your own
    task_tracker list incomplete" instruction: inspect the agent's own
    task_tracker state directly instead of trusting its finish message —
    the same "verify, don't trust the self-report" principle
    `_verify_and_report` already applies to test results (see DECISIONS.md).

    Returns `None` when there's nothing to enforce (the tool was never
    used, or its last known state already has no pending items) so
    `stream_task` proceeds to `_verify_and_report`; returns a terminal
    `TaskOutcome` only if the agent gets stuck/errors mid-retry, the shared
    task-level budget (`deadline`) runs out, or the retry budget is
    exhausted with items still pending. Reuses `cfg.max_verify_retries` as
    the retry budget — the same "how many automatic fix-then-recheck
    cycles are we willing to spend" question `_verify_and_report` already
    answers for test failures, not a second, near-duplicate config knob
    for this closely related concern.
    """
    spent = _budget_spent(conversation, deadline)
    if spent:
        # The budget is checked only between runs, so the agent's last run
        # can end after it. The list needs no model: unfinished items can't
        # be followed up any more, but a finished list leaves the verdict to
        # the project's checks (see _verify_after_budget).
        status = conversation.state.execution_status
        aborted = (
            status in _ABORTED_STATUSES
            and not _hit_step_limit(conversation)
            and conversation not in _CUT_AT_DEADLINE
        )
        snapshot = None if aborted else _task_tracker_snapshot(conversation)
        if aborted or (snapshot is not None and _pending_task_items(snapshot)):
            return TaskOutcome(
                verification_state=spent,
                completion_contract=_exhausted_contract(spent, task, cfg),
            )
        return None

    status = conversation.state.execution_status
    if status in _ABORTED_STATUSES and _hit_step_limit(conversation):
        return None  # the project's checks decide (see _hit_step_limit)
    if status in _ABORTED_STATUSES:
        contract = _build_completion_contract(task, None, skipped=False, aborted=True)
        _emit_notice(
            emit,
            "Certo check: the agent's run ended in a "
            f"'{status.value}' state before its task_tracker completion "
            "could be checked. This task needs manual attention.",
        )
        return TaskOutcome(verification_state="stuck", completion_contract=contract)

    snapshot = _task_tracker_snapshot(conversation)
    if snapshot is None:
        return None
    pending = _pending_task_items(snapshot)
    if not pending:
        return None

    attempts_left = cfg.max_verify_retries
    retries_used = 0
    while pending:
        if attempts_left <= 0:
            contract = _task_tracker_completion_contract(task, pending)
            summary = "; ".join(f"'{item.title}' ({item.status})" for item in pending)
            _emit_notice(
                emit,
                "Certo check: the agent's own task_tracker list still "
                f"shows unfinished item(s) after {cfg.max_verify_retries} "
                f"automated follow-up(s) ({summary}). Giving up — this "
                "task needs manual attention.",
            )
            return TaskOutcome(
                verification_state="incomplete",
                completion_contract=contract,
                retries_used=retries_used,
            )
        attempts_left -= 1
        retries_used += 1
        if model_chain is not None and cfg.execution == "local":
            failed_name = model_chain.current.name
            next_entry = model_chain.advance(
                kind="escalation_quality_failure",
                reason=(
                    f"{failed_name} left its own task_tracker list incomplete after a follow-up."
                ),
            )
            if next_entry is not None:
                _emit_notice(
                    emit,
                    f"Certo: escalating from {failed_name} to {next_entry.name} "
                    "after an incomplete task_tracker follow-up.",
                )
                conversation.switch_llm(
                    llm_for_entry(cfg, next_entry, usage_id=f"certo:{next_entry.name}")
                )
        conversation.send_message(_task_tracker_followup(pending))
        run_result = _run_with_confirmation(
            conversation, cfg, emit, on_confirm, deadline, model_chain
        )
        outcome = _outcome_for_run_result(run_result, task, cfg, retries_used=retries_used)
        if outcome is not None:
            return outcome

        retry_status = conversation.state.execution_status
        if retry_status in _ABORTED_STATUSES and _hit_step_limit(conversation):
            return None  # the project's checks decide (see _hit_step_limit)
        if retry_status in _ABORTED_STATUSES:
            contract = _build_completion_contract(task, None, skipped=False, aborted=True)
            _emit_notice(
                emit,
                "Certo check: the agent got stuck "
                f"(status '{retry_status.value}') while following up on its "
                f"own incomplete task_tracker list, after {retries_used} "
                "attempt(s). This task needs manual attention.",
            )
            return TaskOutcome(
                verification_state="stuck",
                completion_contract=contract,
                retries_used=retries_used,
            )

        snapshot = _task_tracker_snapshot(conversation) or []
        pending = _pending_task_items(snapshot)

    return None


def _write_independent_tests(
    task: str,
    writer_cfg: Config,
    cfg: Config,
    emit: Callable[[Message], None],
    *,
    resuming: bool = False,
) -> TestSets | None:
    """CERTO_INDEPENDENT_TESTS: have `writer_cfg`'s model write
    `cfg.independent_tests_sets` sets of tests before the build, each by its
    own writer, from the task and the project as it is now, into a folder
    outside the project. None when the setting is off, or the run can't
    have them (Docker: the tests run on this computer; a resume: the
    project already holds earlier work)."""
    if not cfg.independent_tests:
        return None
    if cfg.execution != "local":
        _emit_notice(emit, "Certo: independent tests are for local runs only; skipped.")
        return None
    if resuming:
        _emit_notice(
            emit,
            "Certo: independent tests aren't written on --resume (the project already "
            "holds earlier work); skipped.",
        )
        return None
    count = cfg.independent_tests_sets
    sets = "a set" if count == 1 else f"{count} sets"
    _emit_notice(
        emit, f"Certo: writing {sets} of independent tests from the task with {writer_cfg.model}."
    )
    scratch = Path(tempfile.mkdtemp(prefix="certo-independent-tests-"))
    # A local model server answers one request at a time: write one by one.
    written = write_test_sets(
        task,
        writer_cfg,
        scratch,
        count=count,
        project=Path(cfg.workspace),
        parallel=not is_local(writer_cfg),  # model and base_url are all it reads
    )
    for k, one in enumerate(written.sets, start=1):
        which = "" if count == 1 else f" in set {k}"
        if one.runnable:
            _emit_notice(
                emit,
                f"Certo: independent tests written{which} ({', '.join(one.files)}); the agent "
                "won't see them.",
            )
        else:
            _emit_notice(emit, f"Certo: no independent tests{which}: {one.reason}")
    return written


def _apply_independent_tests(
    outcome: TaskOutcome,
    written: TestSets | None,
    cfg: Config,
    keep_in: str | None = None,
) -> TaskOutcome:
    """Run the independent tests on the finished project and attach the
    result. `verification_state` stays as it is (see
    `_apply_strict_independent_tests`). The tests are copied to `keep_in`
    (the run's records folder, never the project, so a later task's agent
    can't see them; one folder per set when there are several), then the
    scratch folder is removed."""
    if written is None:
        return outcome
    try:
        result = run_test_sets(written, cfg.workspace)
    except Exception as exc:  # noqa: BLE001 - report only, never the run's outcome
        result = IndependentTestsResult("error", f"{type(exc).__name__}: {exc}", written.model)
    finally:
        if keep_in is not None:
            target = Path(keep_in) / "independent_tests"
            try:
                for k, one in enumerate(written.sets, start=1):
                    where = target if len(written.sets) == 1 else target / f"set{k}"
                    shutil.copytree(one.folder, where, dirs_exist_ok=True)
            except OSError:
                logger.warning("Could not keep the independent tests", exc_info=True)
        shutil.rmtree(written.scratch, ignore_errors=True)
    return replace(outcome, independent_tests=result)


def _apply_strict_independent_tests(
    outcome: TaskOutcome, cfg: Config, emit: Callable[[Message], None]
) -> TaskOutcome:
    """CERTO_INDEPENDENT_TESTS_STRICT: a `verified` run whose independent
    tests failed (most sets; never `split`, `none` or `error`) becomes
    `independent_failed`. Applied last, after the acceptance checks, so a
    run that fails both reports the user's own check first."""
    result = outcome.independent_tests
    if not (
        cfg.independent_tests_strict
        and outcome.verification_state == "verified"
        and result is not None
        and result.status == "failed"
    ):
        return outcome
    _emit_notice(
        emit,
        "Certo: the project's checks passed, but the independent tests failed "
        f"({result.summary}). Not reporting this as verified "
        "(CERTO_INDEPENDENT_TESTS_STRICT).",
    )
    return replace(outcome, verification_state="independent_failed")


def _apply_acceptance_checks(
    outcome: TaskOutcome,
    cfg: Config,
    emit: Callable[[Message], None],
    checks: Sequence[AcceptanceCheck] | None,
) -> TaskOutcome:
    """Evaluate caller-supplied `acceptance_checks` against `cfg.workspace`
    and fold the results into `outcome` — applied once, as the very last
    step of `stream_task`, to whichever `TaskOutcome` came back from any
    phase (initial run, task_tracker, or project verification).

    A no-op when `checks` is empty/`None` — this feature is opt-in
    (`acceptance.py`'s own scope note applies: only `file_exists`/
    `file_contains` kinds exist, deliberately no command-execution kind),
    so a caller that never supplies `acceptance_checks` sees zero behavior
    change. Evaluated regardless of `verification_state` — even a stuck or
    incomplete run's workspace is still worth reporting on — but only
    overrides `verification_state` itself when it would otherwise be
    `"verified"` and a *required* check failed: every other state already
    represents some other failure, so there's nothing left to "block".
    """
    if not checks:
        return outcome

    results = evaluate_acceptance_checks(cfg.workspace, checks)
    failed_required = [r for r in results if r.check.required and not r.passed]

    criteria = list(outcome.completion_contract.acceptance_criteria)
    limitations = list(outcome.completion_contract.limitations)
    for result in results:
        label = result.check.description or f"{result.check.kind} {result.check.path}"
        criteria.append(label)
        if not result.passed:
            kind_text = "Required" if result.check.required else "Optional"
            limitations.append(f"{kind_text} acceptance check failed ({label}): {result.detail}")

    new_state = outcome.verification_state
    if failed_required and outcome.verification_state == "verified":
        new_state = "acceptance_failed"
        summary = "; ".join(
            f"{r.check.description or r.check.path}: {r.detail}" for r in failed_required
        )
        _emit_notice(
            emit,
            "Certo acceptance check: the project's own tests/build passed, "
            f"but {len(failed_required)} required acceptance check(s) failed "
            f"({summary}). Not reporting this as verified.",
        )

    contract = replace(
        outcome.completion_contract, acceptance_criteria=criteria, limitations=limitations
    )
    return replace(
        outcome,
        verification_state=new_state,
        completion_contract=contract,
        acceptance_results=tuple(results),
    )


def stream_task(
    task: str,
    cfg: Config | None = None,
    on_message: Callable[[Message], None] | None = None,
    on_confirm: ConfirmCallback | None = None,
    acceptance_checks: Sequence[AcceptanceCheck] | None = None,
    on_awaiting_input: OnAwaitingInput | None = None,
    on_model_choice: OnModelChoice | None = None,
    run_id: str | None = None,
    project: str | None = None,
    save_state: bool = False,
    resume_from: RunRecord | None = None,
    resume_instruction: str | None = None,
    ladder: ResolvedLadder | None = None,
    on_escalate: OnEscalate | None = None,
    on_progress: Callable[[str], None] | None = None,
    model_catalog: ModelCatalog | None = None,
) -> TaskOutcome:
    """Run a task, invoking `on_message` with each message as it's produced,
    and return the terminal `TaskOutcome` once verification has settled.

    Shared by `run_task` (collects into a list) and the server's WebSocket
    endpoint (pushes each message to the client as it arrives). `on_confirm`
    is only consulted when `cfg.confirm_mode == "always"` (see
    `_run_with_confirmation`); `cli.py` supplies a real terminal-prompting
    implementation, `server.py` leaves it unset. `acceptance_checks` is
    entirely optional — see `_apply_acceptance_checks`. `on_awaiting_input`
    is only consulted when `cfg.interactive` is true, and only around the
    *initial* run — see the interactive loop below and DECISIONS.md
    for why task_tracker/verification retries stay fully
    autonomous even in interactive mode. `on_model_choice` is only consulted
    when both `cfg.model_selection == "auto"` and `cfg.interactive` are
    true — see model_selection.py's `ModelChain` for the deterministic
    scoring/fallback-chain design. `run_id` names this run's subfolder under
    `CERTO_ARTIFACTS_DIR` (see `artifacts.py`) — `server.py` passes its
    own `TaskRecord.id` so a task's artifacts folder matches `GET
    /tasks/{id}`; every other caller gets one minted automatically when
    `cfg.artifacts_dir` is set. Has no effect at all when it's unset.
    `project` is the same project name `cli.py --project`/`server.py`'s
    `project` request field already resolve into `cfg.workspace` before
    calling this. `Config` has no field for the name itself (only the
    already-resolved workspace path), so a caller that knows it passes it
    again here, purely to bucket this run's artifacts folder the same way
    `CERTO_PROJECTS_DIR` is bucketed.

    `save_state` keeps the run's state in the workspace's `.certo/` folder
    (see project_state.py); only `cli.py` sets it, so server tasks and
    benchmark runs leave no such folder. `resume_from` continues the run that
    record describes: `task` must be its task, and `resume_instruction` is an
    optional extra message from the user. A resume always saves state.

    `ladder` (or `cfg.model_selection == "escalate"`, which resolves one from
    the model files) runs the task as an escalation: see
    `_stream_escalation`. `on_escalate` is asked before each climb when
    `cfg.interactive` is set; `on_progress` receives the escalation lines
    (the ladder, each climb) for a terminal.
    """
    # Total running time covers the whole task, model selection and
    # verification included (and any interactive waits — it is wall clock).
    run_started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    if cfg is None:
        cfg = load_config()
    quiet_sdk_logs(cfg)
    emit = on_message or (lambda _msg: None)
    checkpoint_buffer: list[Message] = []
    all_messages: list[Message] = []
    if not (save_state or resume_from is not None):
        # Checkpoints live in `.certo/` too: a run that keeps no state
        # there (the library default, the benchmark) takes none.
        cfg = replace(cfg, checkpoints=False)

    condensed = [0]

    def on_event(event: Event) -> None:
        if isinstance(event, LLMConvertibleEvent):
            message = event.to_llm_message()
            checkpoint_buffer.append(message)
            all_messages.append(message)
            emit(message)
        elif isinstance(event, Condensation):
            condensed[0] += 1
            _emit_notice(
                emit,
                "Certo: the conversation nearly filled the model's context window, so older "
                "steps were summarized (the task and the latest steps are kept).",
            )

    if ladder is None and cfg.model_selection == "escalate":
        ladder = load_ladder(
            cfg.models_file,
            cfg.models_list_file,
            cfg.escalation_ladder or None,
            escalation_file=cfg.escalation_file,
            task_profiles_file=cfg.task_profiles_file,
            on_warning=lambda w: _emit_notice(emit, f"Certo: models.yaml: {w}"),
        )
    if ladder is not None:
        return _stream_escalation(
            task,
            cfg,
            ladder,
            _EscalationIO(
                emit=emit,
                on_event=on_event,
                checkpoint_buffer=checkpoint_buffer,
                all_messages=all_messages,
                on_confirm=on_confirm,
                on_awaiting_input=on_awaiting_input,
                on_escalate=on_escalate,
                on_progress=on_progress,
                condensed=condensed,
            ),
            acceptance_checks=acceptance_checks,
            run_id=run_id,
            project=project,
            save_state=save_state,
            run_started=run_started,
            started_at=started_at,
        )

    # CERTO_MODEL_SELECTION=auto: pick the best-fit catalog candidate for
    # this task before the Agent/Conversation is even built. The rest of
    # this function keeps using `cfg` unchanged (workspace, execution,
    # confirm_mode, verify_tests, ...) — only the Agent's own LLM is built
    # from a catalog entry's config (see model_selection.config_for_entry).
    model_chain: ModelChain | None = None
    agent_cfg = cfg
    agent_usage_id = "certo"
    if cfg.model_selection == "auto":
        # `model_catalog`: the benchmark's own, already loaded and checked,
        # perhaps narrowed to an arm's models (bench_strategies.py).
        catalog = model_catalog or load_checked_catalog(
            cfg.models_file,
            cfg.models_list_file,
            task_profiles_file=cfg.task_profiles_file,
            escalation_file=cfg.escalation_file,
            on_warning=lambda w: _emit_notice(emit, f"Certo: models.yaml: {w}"),
            mode="auto",
        )
        profile = classify_task(task, catalog)
        ranked, how = rank_for_profile(catalog, profile)
        chosen_index = 0
        trigger = find_trigger(task, profile)
        matched = (
            f'"{trigger}" in the task\'s first line ({task_title(task)!r})'
            if trigger
            else "no profile's trigger in the task's first line"
        )
        reason = (
            f"Task classified as '{profile.name}': {matched} (weights: {profile.weights}). "
            f"Model order: {how}."
        )
        if cfg.interactive and on_model_choice is not None:
            chosen_index = on_model_choice(ranked, 0, reason)
        model_chain = ModelChain(
            ranked, task_profile=profile.name, weights=profile.weights, start_index=chosen_index
        )
        model_chain.record_initial(reason)
        entry = model_chain.current
        agent_cfg = config_for_entry(cfg, entry)
        agent_usage_id = f"certo:{entry.name}"

    # Before the build: the writer sees the project as it is now.
    written = _write_independent_tests(task, agent_cfg, cfg, emit, resuming=resume_from is not None)
    _checkpoint(cfg, "before the resumed run" if resume_from is not None else "before the agent")

    with build_workspace(cfg) as workspace:
        runner = _command_runner(cfg, workspace)
        project_env = _prepare_agent_env(task, cfg, runner, emit)
        _warn_small_window(agent_cfg, emit)

        def new_conversation(**persistence: Any) -> Conversation:
            return Conversation(
                agent=build_agent(
                    agent_cfg,
                    usage_id=agent_usage_id,
                    project_env=project_env,
                    terminal_env=terminal_env(project_env, runner),
                ),
                callbacks=[on_event],
                workspace=workspace,
                visualizer=visualizer_for(agent_cfg),
                # Previously unset (SDK default 500), so CERTO_MAX_ITERATIONS
                # was parsed/validated but silently had no effect — found while
                # bounding the verify-and-retry loop above, which reuses the same
                # conversation.run() and needed this to actually mean something.
                max_iteration_per_run=cfg.max_iterations,
                **persistence,
            )

        state_writer: _ProjectStateWriter | None = None
        first_message: str | None = None
        if save_state or resume_from is not None:
            model_name = model_chain.current.model if model_chain is not None else agent_cfg.model
            conversation, state_writer, first_message = _open_saved_conversation(
                new_conversation,
                cfg,
                task,
                model_name,
                agent_cfg.reasoning_effort,
                resume_from,
                resume_instruction,
                emit,
            )
        else:
            conversation = new_conversation()
        if cfg.confirm_mode == "always":
            # Previously parsed/validated in config.py but never attached to
            # an actual ConfirmationPolicyBase, so it was a silent no-op —
            # see DECISIONS.md. AlwaysConfirm pauses before every tool call;
            # _run_with_confirmation resolves each pause via on_confirm.
            conversation.set_confirmation_policy(AlwaysConfirm())
        # CERTO_MAX_TASK_COST covers the whole task, the tests written
        # before the build included (cost_limit.py).
        set_cost_limit(conversation, cfg.max_task_cost, _metrics_cost(written))
        # A shared, task-level wall-clock budget spanning every phase below —
        # CERTO_MAX_ITERATIONS alone only bounds a single conversation.run()
        # call, and runner.py can call that up to three times per task (this
        # initial run, then up to max_verify_retries more in each of the two
        # retry loops below), each getting its own fresh iteration budget
        # from the SDK. See _run_with_confirmation's docstring and
        # DECISIONS.md for the exact multiplication this closes.
        deadline = time.monotonic() + cfg.max_task_seconds

        # CERTO_ARTIFACTS_DIR: mint a run id up front (server.py passes its
        # own TaskRecord.id instead, so a task's folder matches GET
        # /tasks/{id}) and record wall-clock start — a no-op when unset.
        if cfg.artifacts_dir:
            run_id = run_id or str(uuid.uuid4())

        outcome: TaskOutcome | None = None
        captured_error: BaseException | None = None
        try:
            outcome = _run_stream_task_phases(
                conversation,
                cfg,
                emit,
                task,
                on_confirm,
                on_awaiting_input,
                deadline,
                model_chain,
                checkpoint_buffer,
                runner,
                first_message,
                _on_verification(cfg, state_writer),
                check_changes=resume_from is None,
            )
            outcome = _apply_independent_tests(
                outcome,
                written,
                cfg,
                resolve_run_artifacts_dir(cfg.artifacts_dir, project, run_id)
                if cfg.artifacts_dir and run_id
                else None,
            )
            # The last steps that can change the verdict, inside the `try`
            # so the run record below holds the verdict the caller gets.
            outcome = _apply_acceptance_checks(outcome, cfg, emit, acceptance_checks)
            outcome = _apply_strict_independent_tests(outcome, cfg, emit)
        except BaseException as exc:  # recorded for artifacts.py, then always re-raised as-is
            captured_error = exc
            raise
        finally:
            if written is not None:  # already gone after a normal finish
                shutil.rmtree(written.scratch, ignore_errors=True)
            if state_writer is not None and captured_error is not None:
                state_writer.fail(captured_error)
            # Written even when a phase raises (e.g. every candidate in an
            # auto-selection chain failed at the API level) — that's exactly
            # when the escalation history matters most for debugging. See
            # the live repro this fixed in DECISIONS.md.
            if model_chain is not None:
                write_model_decisions(cfg.workspace, model_chain.decisions)
            per_model_metrics = _per_model_metrics(conversation)
            efforts = _usage_efforts(cfg, agent_cfg, model_chain)
            if written is not None:
                per_model_metrics.update(written.metrics)
                efforts.update(dict.fromkeys(written.usage_ids, agent_cfg.reasoning_effort))
            run_summary = summarize_run(
                time.monotonic() - run_started, per_model_metrics, efforts, condensed[0]
            )
            if captured_error is not None:
                # The exception is the only value that leaves this function
                # on a failed run, so the usage recorded up to the error
                # travels on it: `certo bench` records the tokens an
                # interrupted run really used instead of zeros (see
                # bench.execute_run). Plain attribute, so the exception's
                # type and message stay exactly what the caller expects.
                _attach_run_summary(captured_error, run_summary)
            if cfg.artifacts_dir:
                stats = conversation.conversation_stats
                write_run_artifacts(
                    artifacts_dir=cfg.artifacts_dir,
                    run_id=run_id,
                    project=project,
                    task=task,
                    execution=cfg.execution,
                    model=(
                        model_chain.current.model if model_chain is not None else agent_cfg.model
                    ),
                    reasoning_effort=(
                        config_for_entry(cfg, model_chain.current).reasoning_effort
                        if model_chain is not None
                        else agent_cfg.reasoning_effort
                    ),
                    model_selection=cfg.model_selection,
                    started_at=started_at,
                    ended_at=datetime.now(UTC).isoformat(),
                    messages=[m.model_dump(mode="json") for m in all_messages],
                    outcome=outcome,
                    error=(str(captured_error) if captured_error is not None else None),
                    combined_metrics=stats.get_combined_metrics().get(),
                    per_model_metrics=per_model_metrics,
                    run_summary=run_summary.to_dict(),
                )
        if model_chain is not None:
            outcome = replace(outcome, model_decisions=tuple(model_chain.decisions))
        outcome = replace(outcome, tool_call_reminders=_reminders_sent(conversation))
        if state_writer is not None:
            state_writer.finish(outcome)
        _checkpoint(cfg, f"finished: {outcome.verification_state}")
        return replace(outcome, run_summary=run_summary)


def _attach_run_summary(error: BaseException, summary: RunSummary) -> None:
    """Carry a failed run's partial usage on its exception.

    `certo bench` reads `run_summary` off the exception to record the
    tokens a run used before it failed (see bench.execute_run). An
    exception class that refuses attributes just keeps the old zeros,
    never hides the run's own error.
    """
    try:
        setattr(error, "run_summary", summary)
    except Exception:  # noqa: BLE001 - the run's error must win
        pass


def _checkpoint(cfg: Config, label: str) -> None:
    """CERTO_CHECKPOINTS: snapshot the project (checkpoints.py), best effort."""
    if cfg.checkpoints:
        safe_snapshot(cfg.workspace, label)


def _on_verification(
    cfg: Config, state_writer: _ProjectStateWriter | None, prefix: str = ""
) -> Callable[[VerificationRun], None]:
    """After every check run: `.certo/` state, and a checkpoint labelled
    with the check run's number and result (`prefix` names the rung)."""
    count = 0

    def on_verification(run: VerificationRun) -> None:
        nonlocal count
        count += 1
        if state_writer is not None:
            state_writer.on_verification(run)
        _checkpoint(cfg, f"{prefix}checks {count}: {run.state}")

    return on_verification


class _ProjectStateWriter:
    """Keeps `.certo/` up to date during one run (see project_state.py).

    Every write is best effort: a full disk or a read-only folder is logged
    and must never change the run's own outcome.
    """

    def __init__(self, workspace: str, record: RunRecord) -> None:
        self.workspace = workspace
        self.record = record

    def save(self) -> None:
        try:
            save_record(self.workspace, self.record)
        except OSError:
            logger.warning("Could not save the run state in .certo/", exc_info=True)

    def on_verification(self, run: VerificationRun) -> None:
        self.record.checks = checks_from_outcomes(run.checks)
        self.save()

    def finish(self, outcome: TaskOutcome) -> None:
        self.record.status = "finished"
        self.record.verdict = outcome.verification_state
        self.record.retries_used = outcome.retries_used
        if outcome.checks:
            self.record.checks = checks_from_outcomes(outcome.checks)
        self.record.limitations = list(outcome.completion_contract.limitations)
        self.save()

    def fail(self, exc: BaseException) -> None:
        if isinstance(exc, KeyboardInterrupt):
            self.record.status = "interrupted"
        else:
            self.record.status = "error"
            self.record.error = str(exc) or type(exc).__name__
        self.save()


def _open_saved_conversation(
    new_conversation: Callable[..., Conversation],
    cfg: Config,
    task: str,
    model: str,
    effort: str | None,
    resume_from: RunRecord | None,
    instruction: str | None,
    emit: Callable[[Message], None],
) -> tuple[Conversation, _ProjectStateWriter | None, str | None]:
    """The conversation for a run that saves its state, the writer that
    keeps `.certo/` current, and the first message when resuming.

    A resume reloads the SDK's saved conversation when it can, so the agent
    keeps its context. When it can't (Docker, where the SDK takes no
    persistence folder; a missing folder; a conversation the SDK refuses to
    load), it starts a new conversation whose first message carries the task
    and `STATUS.md` instead.
    """
    workspace = cfg.workspace
    try:
        ensure_state_dir(workspace)
    except OSError as exc:
        if resume_from is not None:
            raise
        _emit_notice(emit, f"Certo: can't save the run state in .certo/ ({exc}); continuing.")
        return new_conversation(), None, None
    persist = cfg.execution == "local"
    conversation: Conversation | None = None
    has_context = False
    if resume_from is not None:
        saved_id = resume_from.conversation_id
        if not persist:
            reason = "Docker runs don't save the conversation"
        elif not has_saved_conversation(workspace, saved_id):
            reason = "it isn't in .certo/ any more"
        else:
            reason = ""
            try:
                conversation = new_conversation(
                    persistence_dir=conversations_dir(workspace),
                    conversation_id=uuid.UUID(hex=saved_id),
                )
                has_context = True
            except Exception as exc:  # noqa: BLE001 - any load failure falls back to STATUS.md
                reason = f"it couldn't be loaded: {exc}"
        if reason:
            _emit_notice(
                emit,
                f"Certo: resuming without the earlier conversation ({reason}); "
                "the agent gets the task, .certo/STATUS.md and the files.",
            )
    if conversation is None:
        new_id = uuid.uuid4()
        conversation = (
            new_conversation(persistence_dir=conversations_dir(workspace), conversation_id=new_id)
            if persist
            else new_conversation()
        )
        conversation_id = new_id.hex
    else:
        conversation_id = resume_from.conversation_id

    first_message = None
    if resume_from is not None:
        record = replace(resume_from)  # a copy: the caller's record stays as it was
        first_message = resume_message(record, instruction, has_context=has_context)
        record.status = "running"
        record.verdict = None
        record.error = None
        record.retries_used = 0
        record.resumes += 1
        record.conversation_id = conversation_id
        record.model = model
        record.reasoning_effort = effort
        record.execution = cfg.execution
    else:
        record = RunRecord(
            task=task,
            conversation_id=conversation_id,
            model=model,
            reasoning_effort=effort,
            execution=cfg.execution,
            started_at=now(),
            updated_at=now(),
        )
    drop_other_conversations(workspace, keep=conversation_id)
    writer = _ProjectStateWriter(workspace, record)
    writer.save()
    return conversation, writer, first_message


def _usage_efforts(
    cfg: Config, agent_cfg: Config, model_chain: ModelChain | None
) -> dict[str, str | None]:
    """Each usage_id's reasoning effort, for the run summary: the agent's
    own, and every auto-model candidate's (a fallback gets its own
    usage_id)."""
    efforts = {"certo": agent_cfg.reasoning_effort}
    if model_chain is not None:
        for entry in model_chain.candidates:
            efforts[f"certo:{entry.name}"] = config_for_entry(cfg, entry).reasoning_effort
    return efforts


def _metrics_cost(written: Any) -> float:
    """What writing the independent tests cost, in USD (0 without them)."""
    if written is None:
        return 0.0
    costs = (m.get("accumulated_cost") for m in written.metrics.values())
    return sum(float(c) for c in costs if isinstance(c, int | float))


def _per_model_metrics(conversation: Conversation) -> dict[str, dict]:
    """`{usage_id: Metrics.get()}` from the SDK's conversation stats.

    Called from stream_task's `finally`: a failure here must degrade to "no
    metrics" rather than replace the run's own outcome or exception.
    """
    try:
        return {
            usage_id: metrics.get()
            for usage_id, metrics in conversation.conversation_stats.usage_to_metrics.items()
        }
    except Exception:
        logger.warning("Could not read conversation metrics for the run summary", exc_info=True)
        return {}


def _run_stream_task_phases(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    task: str,
    on_confirm: ConfirmCallback | None,
    on_awaiting_input: OnAwaitingInput | None,
    deadline: float,
    model_chain: ModelChain | None,
    checkpoint_buffer: list[Message],
    runner: CommandRunner | None = None,
    first_message: str | None = None,
    on_verification: Callable[[VerificationRun], None] | None = None,
    check_changes: bool = True,
) -> TaskOutcome:
    """The initial run, the interactive checkpoint loop, and the two
    autonomous retry phases — split out of `stream_task` purely so the
    `finally: write_model_decisions(...)` wrapping it can run regardless of
    which phase raises, without an extra indent level for all of it.

    `check_changes` turns a `verified` run that changed no file into one
    follow-up and then, if still nothing changed, `unchanged` (see
    `_require_a_change`). A resume passes False: its changes may come from
    the earlier session.
    """
    before = workspace_listing(cfg.workspace) if check_changes else None
    check_files_before = snapshot_check_files(cfg.workspace)
    # `first_message` is a resume's message; `task` stays the goal that
    # verification and the completion contract are judged against.
    conversation.send_message(first_message or task)
    run_result = _run_with_confirmation(conversation, cfg, emit, on_confirm, deadline, model_chain)
    outcome = _outcome_for_run_result(run_result, task, cfg)

    # CERTO_INTERACTIVE=yes, initial run only (see stream_task's
    # docstring and DECISIONS.md): the SDK can't tell a
    # genuine clarifying question apart from real completion — both set
    # execution_status = FINISHED identically (see agent.py's
    # _AUTONOMOUS_SUFFIX docstring) — so rather than guessing, always
    # offer the human a checkpoint here and let them decide. Has no
    # effect without a caller-supplied on_awaiting_input (server.py
    # never supplies one; cfg.interactive alone is not enough).
    while (
        outcome is None
        and cfg.interactive
        and on_awaiting_input is not None
        and conversation.state.execution_status == ConversationExecutionStatus.FINISHED
    ):
        narrative = _narrative_text(checkpoint_buffer)
        checkpoint_buffer.clear()
        wait_started = time.monotonic()
        reply = on_awaiting_input(narrative)
        # Time spent waiting on the human doesn't count against the
        # shared task budget — only actual agent run time should.
        deadline += time.monotonic() - wait_started
        if not reply:
            break
        conversation.send_message(reply)
        run_result = _run_with_confirmation(
            conversation, cfg, emit, on_confirm, deadline, model_chain
        )
        outcome = _outcome_for_run_result(run_result, task, cfg)

    if outcome is None:
        outcome = _enforce_task_tracker_completion(
            conversation, cfg, emit, task, on_confirm, deadline, model_chain
        )
    if outcome is None:
        outcome = _verify_and_report(
            conversation,
            cfg,
            emit,
            task,
            on_confirm,
            deadline,
            model_chain,
            runner,
            on_verification,
            before,
        )
    if before is not None and outcome.verification_state == "verified":
        outcome = _require_a_change(
            conversation,
            cfg,
            emit,
            task,
            on_confirm,
            deadline,
            model_chain,
            runner,
            on_verification,
            before,
            outcome,
        )
    if outcome.verification_state == "verified":
        outcome = _note_check_file_changes(cfg.workspace, check_files_before, outcome)
    return outcome


def _note_check_file_changes(
    workspace: str, before: dict[str, bytes], outcome: TaskOutcome
) -> TaskOutcome:
    """A `verified` run that changed the files its checks rely on says so,
    with the lines changed, removed and added (check_files.py). The verdict stays:
    the task may have asked for the change."""
    changes = check_file_changes(workspace, before)
    if not changes:
        return outcome
    contract = outcome.completion_contract
    limitations = [*contract.limitations, changes_note(changes)]
    return replace(
        outcome,
        check_file_changes=changes,
        completion_contract=replace(contract, limitations=limitations),
    )


# Files Certo itself writes in the project folder; they never count as the
# agent's change. (`.certo/` and environments are skipped by the listing.)
_CERTO_OWN_FILES = frozenset({"MODEL_DECISIONS.md"})


def _agent_changed_files(workspace: str, before: dict[str, tuple[int, int]]) -> bool:
    changes = FileChanges.between(before, workspace_listing(workspace))
    paths = changes.created + changes.modified + changes.deleted
    return any(p not in _CERTO_OWN_FILES for p in paths)


def _unchanged_followup(workspace: str) -> str:
    return (
        "Certo checked the project folder after you finished: no file in it "
        "changed during this run. The project's checks pass, but they passed "
        "before you started too, so they say nothing about this task. If the "
        "task needs changes, make them now, in this folder "
        f"({os.path.abspath(workspace)}), and finish again. If it truly needs "
        "no change, finish again and say why."
    )


def _require_a_change(
    conversation: Conversation,
    cfg: Config,
    emit: Callable[[Message], None],
    task: str,
    on_confirm: ConfirmCallback | None,
    deadline: float,
    model_chain: ModelChain | None,
    runner: CommandRunner | None,
    on_verification: Callable[[VerificationRun], None] | None,
    before: dict[str, tuple[int, int]],
    outcome: TaskOutcome,
) -> TaskOutcome:
    """A `verified` run that changed no file proves only that the folder
    passed its checks before the agent started. Ask the agent once (it may
    have stopped early, or written somewhere else); if a file changes,
    verify again as usual. If still nothing changed, the verdict is
    `unchanged`: the agent's reason, if it gave one, is not proof (golden
    rule 7), and a task that really needs no change is still possible, so
    it is not a failure either. Found by the first complete benchmark: a
    local model ended a "fix and extend" task with no edit, and the
    starter's own tests passed."""
    if _agent_changed_files(cfg.workspace, before):
        return outcome
    _emit_notice(
        emit,
        "Certo: the agent changed no file in the project folder, so the passing "
        "checks say nothing about this task. Asking it once to do the task or say why "
        "no change is needed.",
    )
    retries_used = outcome.retries_used + 1
    conversation.send_message(_unchanged_followup(cfg.workspace))
    run_result = _run_with_confirmation(conversation, cfg, emit, on_confirm, deadline, model_chain)
    stopped = _outcome_for_run_result(
        run_result, task, cfg, checks=outcome.checks, retries_used=retries_used
    )
    if stopped is not None:
        return stopped
    again = _verify_and_report(
        conversation,
        cfg,
        emit,
        task,
        on_confirm,
        deadline,
        model_chain,
        runner,
        on_verification,
        before,
    )
    again = replace(again, retries_used=again.retries_used + retries_used)
    if again.verification_state != "verified" or _agent_changed_files(cfg.workspace, before):
        return again
    _emit_notice(
        emit,
        "Certo verification: the agent still changed no file. The checks pass, as they "
        "did before it started, so this is reported as unchanged, not verified.",
    )
    limitations = [
        *again.completion_contract.limitations,
        (
            "The agent changed no file in the project folder, even after Certo asked once. "
            "The checks passed on the folder as it was before the run, so they don't show "
            "that the task was done."
        ),
    ]
    return replace(
        again,
        verification_state="unchanged",
        completion_contract=replace(again.completion_contract, limitations=limitations),
    )


# Asked before each climb under CERTO_INTERACTIVE: the question (who
# couldn't finish, the next model, the cost so far and an estimate) ->
# whether to climb. cli.py prompts at the terminal; server.py never asks.
OnEscalate = Callable[[str], bool]


@dataclass
class _EscalationIO:
    """The callbacks and message buffers `stream_task` shares with
    `_stream_escalation`."""

    emit: Callable[[Message], None]
    on_event: Callable[[Event], None]
    checkpoint_buffer: list[Message]
    all_messages: list[Message]
    on_confirm: ConfirmCallback | None
    on_awaiting_input: OnAwaitingInput | None
    on_escalate: OnEscalate | None
    on_progress: Callable[[str], None] | None
    # How many times the condenser summarized older steps, over every rung.
    condensed: list[int] = field(default_factory=lambda: [0])

    def notify(self, text: str) -> None:
        """An escalation line: a notice in the transcript, and printed."""
        _emit_notice(self.emit, text)
        if self.on_progress is not None:
            self.on_progress(text)


def _rung_config(cfg: Config, rung: Rung) -> Config:
    """`cfg` with the rung's model, and its own reasoning effort and
    fix-attempt budget when the ladder sets them."""
    rung_cfg = config_for_entry(cfg, rung.entry)
    if rung.reasoning_effort:
        rung_cfg = override_llm(rung_cfg, reasoning_effort=rung.reasoning_effort)
    if rung.retries is not None:
        rung_cfg = replace(rung_cfg, max_verify_retries=rung.retries)
    return rung_cfg


def _is_rung_failure(exc: ConversationRunError, cfg: Config) -> bool:
    """Whether a run error ends the rung (and moves to the next one) rather
    than the whole task. Locally only a provider failure (the SDK's
    `LLMError`) does; a remote (Docker) conversation wraps every failure in
    a server error, so there any run error counts."""
    if cfg.execution != "local":
        return True
    return isinstance(exc.original_exception, LLMError)


def _failing(outcome: TaskOutcome | None) -> list[CheckOutcome]:
    if outcome is None:
        return []
    return [c for c in outcome.checks if c.status in ("failed", "timed_out")]


def _cost_note(rungs: Sequence[RungResult]) -> str:
    spent = sum(r.cost for r in rungs)
    unpriced = [r.name for r in rungs if not r.cost_known]
    note = f"${spent:.4f}"
    if unpriced:
        note += f" (no known price for {', '.join(unpriced)}: counted as 0)"
    return note


def _restart_rung(
    cfg: Config, restart_from: Checkpoint | None, previous: RungResult, io: _EscalationIO
) -> bool:
    """CERTO_ESCALATION_HANDOFF=restart: put the files back as they were
    before the first rung (the previous rung's work is snapshotted first,
    so `certo rollback` can bring it back). False when there is nothing to
    undo, or no checkpoint to restore from: the rung then continues."""
    if cfg.escalation_handoff != "restart":
        return False
    if restart_from is None:
        io.notify(
            "Certo: can't restart from the original files (no checkpoint: is git installed?); "
            "the next model continues from the files as they are."
        )
        return False
    if not (previous.changes.created or previous.changes.modified or previous.changes.deleted):
        return False
    try:
        latest = list_checkpoints(cfg.workspace)[-1]
        kept, _ = rollback(cfg.workspace, restart_from.number)
    except (CheckpointError, OSError, subprocess.SubprocessError) as exc:
        io.notify(f"Certo: couldn't restore the original files ({exc}); the next model continues.")
        return False
    # None: the files already matched the last checkpoint (a check run's).
    where = f" (its work is in checkpoint {(kept or latest).number})"
    io.notify(
        f"Certo: {previous.name}'s changes were undone{where}; the next model starts from "
        "the files as they were before the first model."
    )
    return True


def _escalation_stop_reason(cfg: Config, deadline: float, rungs: Sequence[RungResult]) -> str:
    """Why the next rung must not start, or "" when it may."""
    if time.monotonic() >= deadline:
        return f"the task's time budget (CERTO_MAX_TASK_SECONDS={cfg.max_task_seconds}) is spent"
    if cfg.max_task_cost is not None and sum(r.cost for r in rungs) >= cfg.max_task_cost:
        return (
            f"the cost so far, {_cost_note(rungs)}, has reached CERTO_MAX_TASK_COST="
            f"{cfg.max_task_cost:g}"
        )
    return ""


def _escalation_question(previous: RungResult, nxt: Rung, rungs: Sequence[RungResult]) -> str:
    estimate = estimate_run_cost(nxt.entry)
    if estimate is None:
        price = "no price known"
    elif estimate == 0:
        price = "local, no cost"
    else:
        price = f"roughly ${estimate:.2f} for a run, from LiteLLM's prices"
    return (
        f"{previous.name} couldn't finish ({previous.ended}). Try {nxt.name} next? "
        f"Cost so far: {_cost_note(rungs)}. {nxt.name}: {price}."
    )


def _ladder_reason(ladder: ResolvedLadder) -> str:
    if ladder.kind == "derived":
        reason = (
            "Derived from the active models' ratings: capability is the sum of each "
            f"model's ratings except '{ladder.cost_axis}' (usually reasoning + precision + "
            "code); the best of the cheapest models first, then only models more capable "
            "than every cheaper one; the longest ladder is escalation.max_rungs."
        )
    else:
        reason = f"Explicit ladder '{ladder.name}' from {ladder.source}."
    if ladder.skipped:
        reason += f" Skipped: {', '.join(ladder.skipped)}."
    return reason


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _stream_escalation(
    task: str,
    cfg: Config,
    ladder: ResolvedLadder,
    io: _EscalationIO,
    *,
    acceptance_checks: Sequence[AcceptanceCheck] | None,
    run_id: str | None,
    project: str | None,
    save_state: bool,
    run_started: float,
    started_at: str,
) -> TaskOutcome:
    """Run `task` up `ladder`: each rung is the normal run (verification,
    retries, to-do enforcement) in a fresh conversation with its own model,
    in the same workspace. Stops at the first verdict that doesn't escalate
    (see `ResolvedLadder.escalates_on`), after two rungs in a row that did no
    work (see `RungResult.did_no_work`) or that both ended `inconclusive`,
    at the last rung, when the shared
    time budget or `CERTO_MAX_TASK_COST` is spent, or when the user declines
    a climb. The final verdict is the last rung's.

    The next rung gets the files as they are, the original task, the real
    output of the checks that were failing, and a note Certo writes from
    recorded facts (`escalation.handoff_message`), never the previous
    conversation: it can be huge, and replaying it to an expensive model
    costs money and adds noise. A provider failure ends a rung as well, and
    is recorded as such; on the last rung, or when the climb stops after
    it, the error is raised as in a single-model run.

    MODEL_DECISIONS.md (the ladder, every climb and the stop) and, with
    CERTO_ARTIFACTS_DIR, one artifacts folder per rung plus the combined
    record are written even when a rung raises.
    """
    io.notify("\n".join(describe_ladder(ladder)))
    rungs: list[RungResult] = []
    per_model_metrics: dict[str, dict] = {}
    efforts: dict[str, str | None] = {}  # usage_id -> reasoning effort
    final_outcome: TaskOutcome | None = None
    final_rung: int | None = None
    last_error: BaseException | None = None
    failing_output = ""
    total = len(ladder.rungs)
    scores = tuple((r.label, r.capability) for r in ladder.rungs)
    decisions: list[ModelDecisionRecord] = []
    if cfg.artifacts_dir:
        run_id = run_id or str(uuid.uuid4())

    def decide(kind: str, chosen: str, reason: str) -> None:
        decisions.append(
            ModelDecisionRecord(
                kind=kind,
                timestamp=datetime.now(UTC).isoformat(),
                task_profile="",
                weights={},
                ranked=scores,
                chosen=chosen,
                reason=reason,
                list_title=f"Ladder ({ladder.label})",
                score_label="capability",
            )
        )

    def write_rung_artifacts(result: RungResult, outcome, error, messages, metrics) -> None:
        if not cfg.artifacts_dir:
            return
        write_run_artifacts(
            artifacts_dir=cfg.artifacts_dir,
            run_id=f"{run_id}/rungs/{result.number}-{_safe_name(result.name)}",
            project=project,
            task=task,
            execution=cfg.execution,
            model=result.model,
            reasoning_effort=result.reasoning_effort,
            model_selection="escalate",
            started_at=started_at,
            ended_at=datetime.now(UTC).isoformat(),
            messages=[m.model_dump(mode="json") for m in messages],
            outcome=outcome,
            error=error,
            combined_metrics={},
            per_model_metrics=metrics,
            run_summary=result.summary.to_dict() if result.summary else None,
            rungs=[result.to_dict()],
        )

    decide("ladder", ladder.rungs[0].label, _ladder_reason(ladder))
    # Written once, before the first rung, with its model; they judge the
    # final result, whichever rung produced it.
    first_cfg = _rung_config(cfg, ladder.rungs[0])
    written = _write_independent_tests(task, first_cfg, cfg, io.emit)
    # CERTO_ESCALATION_HANDOFF=restart: every later rung starts from these
    # files, so they are always kept, even when checkpoints are off.
    restart_from = (
        safe_snapshot(cfg.workspace, "before the agent", always=True)
        if cfg.escalation_handoff == "restart"
        else None
    )
    if restart_from is None:
        _checkpoint(cfg, "before the agent")
    if written is not None:
        per_model_metrics.update(written.metrics)
        efforts.update(dict.fromkeys(written.usage_ids, first_cfg.reasoning_effort))
    captured_error: BaseException | None = None
    try:
        with build_workspace(cfg) as workspace:
            runner = _command_runner(cfg, workspace)
            project_env = _prepare_agent_env(task, cfg, runner, io.emit)
            # One budget for every rung together, as for every retry.
            deadline = time.monotonic() + cfg.max_task_seconds
            for number, rung in enumerate(ladder.rungs, start=1):
                rung_cfg = _rung_config(cfg, rung)
                usage_id = f"certo:rung{number}:{rung.name}"
                efforts[usage_id] = rung_cfg.reasoning_effort
                _warn_small_window(rung_cfg, io.emit)

                def new_conversation(
                    rung_cfg: Config = rung_cfg, usage_id: str = usage_id, **persistence: Any
                ) -> Conversation:
                    return Conversation(
                        agent=build_agent(
                            rung_cfg,
                            usage_id=usage_id,
                            project_env=project_env,
                            terminal_env=terminal_env(project_env, runner),
                        ),
                        callbacks=[io.on_event],
                        workspace=workspace,
                        visualizer=visualizer_for(rung_cfg),
                        max_iteration_per_run=rung_cfg.max_iterations,
                        **persistence,
                    )

                state_writer: _ProjectStateWriter | None = None
                if save_state:
                    conversation, state_writer, _ = _open_saved_conversation(
                        new_conversation,
                        rung_cfg,
                        task,
                        rung.entry.model,
                        rung_cfg.reasoning_effort,
                        None,
                        None,
                        io.emit,
                    )
                else:
                    conversation = new_conversation()
                if cfg.confirm_mode == "always":
                    conversation.set_confirmation_policy(AlwaysConfirm())
                # One cost limit for every rung together (cost_limit.py).
                set_cost_limit(
                    conversation,
                    cfg.max_task_cost,
                    _metrics_cost(written) + sum(r.cost for r in rungs),
                )

                restarted = number > 1 and _restart_rung(cfg, restart_from, rungs[-1], io)
                first_message = (
                    None
                    if number == 1
                    else handoff_message(task, rungs, failing_output, restarted=restarted)
                )
                before = workspace_listing(cfg.workspace)
                rung_started = time.monotonic()
                first_message_index = len(io.all_messages)
                io.checkpoint_buffer.clear()
                outcome: TaskOutcome | None = None
                failure: str | None = None
                try:
                    outcome = _run_stream_task_phases(
                        conversation,
                        rung_cfg,
                        io.emit,
                        task,
                        io.on_confirm,
                        io.on_awaiting_input,
                        deadline,
                        None,
                        io.checkpoint_buffer,
                        runner,
                        first_message,
                        _on_verification(cfg, state_writer, f"rung {number} ({rung.name}), "),
                    )
                    outcome = _apply_acceptance_checks(outcome, cfg, io.emit, acceptance_checks)
                except ConversationRunError as exc:
                    if not _is_rung_failure(exc, cfg):
                        if state_writer is not None:
                            state_writer.fail(exc)
                        raise
                    original = exc.original_exception or exc
                    failure = f"{type(original).__name__}: {original}"
                    last_error = exc
                except BaseException as exc:
                    if state_writer is not None:
                        state_writer.fail(exc)
                    raise
                rung_metrics = _per_model_metrics(conversation)
                per_model_metrics.update(rung_metrics)
                failing = _failing(outcome)
                duration = time.monotonic() - rung_started
                result = RungResult(
                    number=number,
                    name=rung.name,
                    model=rung.entry.model,
                    reasoning_effort=rung_cfg.reasoning_effort,
                    verdict=outcome.verification_state if outcome is not None else None,
                    retries_used=outcome.retries_used if outcome is not None else 0,
                    tool_call_reminders=_reminders_sent(conversation),
                    duration_seconds=duration,
                    summary=summarize_run(duration, rung_metrics, efforts),
                    failure=failure,
                    changes=FileChanges.between(before, workspace_listing(cfg.workspace)),
                    failing_checks=tuple(f"{c.name} (`{c.command}`)" for c in failing),
                )
                rungs.append(result)
                write_rung_artifacts(
                    result, outcome, failure, io.all_messages[first_message_index:], rung_metrics
                )
                if state_writer is not None:
                    if outcome is not None:
                        state_writer.finish(outcome)
                    else:
                        state_writer.fail(RuntimeError(failure))
                if outcome is not None:
                    final_outcome, final_rung = outcome, number

                previous = rungs[-2] if len(rungs) > 1 else None
                if result.did_no_work and previous is not None and previous.did_no_work:
                    io.notify(
                        f"Certo: {rung.name} changed no file either, after {previous.name}: two "
                        "models in a row did no work on this task, so escalation stops."
                    )
                    decide(
                        "escalation_stop",
                        rung.label,
                        f"{rung.name} ({result.ended}) and {previous.name} ({previous.ended}) "
                        "both changed no file.",
                    )
                    break
                if (
                    result.verdict == "inconclusive"
                    and previous is not None
                    and previous.verdict == "inconclusive"
                ):
                    io.notify(
                        f"Certo: {rung.name} ended inconclusive too, after {previous.name}: two "
                        "models in a row left nothing Certo could check, so escalation stops. "
                        "Escalation needs a project with something to check, such as tests "
                        "or a build."
                    )
                    decide(
                        "escalation_stop",
                        rung.label,
                        f"{rung.name} and {previous.name} both ended inconclusive.",
                    )
                    break
                if outcome is not None and not ladder.escalates_on(outcome.verification_state):
                    decide(
                        "escalation_stop",
                        rung.label,
                        f"{rung.name} ended {result.ended}, which doesn't escalate.",
                    )
                    break
                stop = (
                    f"it was the last rung ({number} of {total})"
                    if number == total
                    else _escalation_stop_reason(cfg, deadline, rungs)
                )
                nxt = ladder.rungs[number] if number < total else None
                if (
                    not stop
                    and nxt is not None
                    and cfg.interactive
                    and io.on_escalate is not None
                    and not io.on_escalate(_escalation_question(result, nxt, rungs))
                ):
                    stop = "you chose not to try the next model"
                if stop:
                    io.notify(f"Certo: {rung.name} ended {result.ended}; escalation stops: {stop}.")
                    decide(
                        "escalation_stop", rung.label, f"{rung.name} ended {result.ended}; {stop}."
                    )
                    if outcome is None:
                        raise last_error  # type: ignore[misc]
                    break
                line = climb_line(result, nxt, number + 1, total)
                io.notify(line)
                kind = "climb_provider_failure" if outcome is None else "climb_quality_failure"
                reason = line.removeprefix("Certo: ")
                if outcome is None and failure_reason(failure):
                    # The line keeps only the plain reason; the record keeps the error.
                    reason += f" The error: {failure}"
                decide(kind, nxt.label, reason)
                failing_output = "\n\n---\n\n".join(_check_followup(c) for c in failing)
        if final_outcome is not None and final_rung == (rungs[-1].number if rungs else None):
            final_outcome = _apply_independent_tests(
                final_outcome,
                written,
                cfg,
                resolve_run_artifacts_dir(cfg.artifacts_dir, project, run_id)
                if cfg.artifacts_dir and run_id
                else None,
            )
            strict = _apply_strict_independent_tests(final_outcome, cfg, io.emit)
            if strict is not final_outcome and state_writer is not None:
                state_writer.finish(strict)  # STATUS.md says the final verdict
            final_outcome = strict
        if final_outcome is not None:
            _checkpoint(cfg, f"finished: {final_outcome.verification_state}")
    except BaseException as exc:
        captured_error = exc
        raise
    finally:
        if written is not None:  # already gone after a normal finish
            shutil.rmtree(written.scratch, ignore_errors=True)
        write_model_decisions(cfg.workspace, decisions)
        run_summary = summarize_run(
            time.monotonic() - run_started, per_model_metrics, efforts, io.condensed[0]
        )
        if captured_error is not None:
            # The exception is the only value that leaves this function on a
            # failed escalation, so the usage of every rung that ran travels
            # on it: `certo bench` records the tokens an escalation burned
            # before it failed instead of zeros (see bench.execute_run).
            _attach_run_summary(captured_error, run_summary)
        if cfg.artifacts_dir:
            final = final_outcome if captured_error is None else None
            write_run_artifacts(
                artifacts_dir=cfg.artifacts_dir,
                run_id=run_id,
                project=project,
                task=task,
                execution=cfg.execution,
                model=rungs[-1].model if rungs else ladder.rungs[0].entry.model,
                reasoning_effort=(
                    rungs[-1].reasoning_effort
                    if rungs
                    else _rung_config(cfg, ladder.rungs[0]).reasoning_effort
                ),
                model_selection="escalate",
                started_at=started_at,
                ended_at=datetime.now(UTC).isoformat(),
                messages=[m.model_dump(mode="json") for m in io.all_messages],
                outcome=final,
                error=str(captured_error) if captured_error is not None else None,
                combined_metrics={},
                per_model_metrics=per_model_metrics,
                run_summary=run_summary.to_dict(),
                rungs=rung_dicts(rungs, final_rung if captured_error is None else None),
            )

    if final_outcome is None or final_rung != rungs[-1].number:
        # Every rung that ran ended in a provider failure, or the last one did.
        if last_error is not None:
            _attach_run_summary(
                last_error,
                summarize_run(
                    time.monotonic() - run_started, per_model_metrics, efforts, io.condensed[0]
                ),
            )
        raise last_error  # type: ignore[misc]
    return replace(
        final_outcome,
        rungs=tuple(rungs),
        final_rung=final_rung,
        model_decisions=tuple(decisions),
        tool_call_reminders=sum(r.tool_call_reminders for r in rungs),
        run_summary=summarize_run(
            time.monotonic() - run_started, per_model_metrics, efforts, io.condensed[0]
        ),
    )


def run_task(
    task: str,
    cfg: Config | None = None,
    on_confirm: ConfirmCallback | None = None,
    acceptance_checks: Sequence[AcceptanceCheck] | None = None,
    on_awaiting_input: OnAwaitingInput | None = None,
    on_model_choice: OnModelChoice | None = None,
    run_id: str | None = None,
    project: str | None = None,
    save_state: bool = False,
    resume_from: RunRecord | None = None,
    resume_instruction: str | None = None,
    ladder: ResolvedLadder | None = None,
    on_escalate: OnEscalate | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_notice: Callable[[str], None] | None = None,
) -> TaskResult:
    """`stream_task`, collecting the messages. `on_notice` receives the text
    of each of Certo's own notices as it happens, for a terminal."""
    messages: list = []

    def on_message(message: Message) -> None:
        messages.append(message)
        if on_notice is not None and is_notice(message):
            for content in message.content:
                text = getattr(content, "text", None)
                if text:
                    on_notice(text)

    outcome = stream_task(
        task,
        cfg=cfg,
        on_message=on_message,
        on_confirm=on_confirm,
        acceptance_checks=acceptance_checks,
        on_awaiting_input=on_awaiting_input,
        on_model_choice=on_model_choice,
        run_id=run_id,
        project=project,
        save_state=save_state,
        resume_from=resume_from,
        resume_instruction=resume_instruction,
        ladder=ladder,
        on_escalate=on_escalate,
        on_progress=on_progress,
    )
    return TaskResult(messages, outcome)  # last message is the final assistant output
