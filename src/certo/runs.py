"""Runs that a caller starts and then follows: the MCP server's `run_task`,
`run_status`, `run_events` and `run_cancel` (DECISIONS.md, "The MCP server:
every command, on a shared core", point 4).

`RunManager.start` prepares the run with `api` (so a wrong setting is refused
at once), then runs it in a thread and returns its id. The run's messages and
Certo's notices are kept as numbered events, read with a cursor. `cancel`
stops it at its next step (cancel.py). One run per project folder at a time;
runs in different folders go in parallel.

Each run keeps its state in the project's `.certo/` folder, so a cancelled or
failed run can be continued with `certo --resume`, and is added to its
`.certo/RUNS.md` as a command-line run is.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from .api import (
    RunOptions,
    RunPlan,
    UsageError,
    load_run_ladder,
    plan_run,
    prepare_workspace,
    resolve_config,
    run_milestones,
)
from .config import Config
from .result import passes, run_result
from .run_history import append_run, run_entry
from .run_report import report_relpath, write_report

logger = logging.getLogger(__name__)

# Events returned by one `events` call, at most.
EVENTS_PER_CALL = 200
# One event's text is cut to this many characters.
EVENT_TEXT_CHARS = 4000

RUN_STATES = ("running", "finished", "cancelled", "error")


class UnknownRun(UsageError):
    """No run has this id."""


@dataclass
class RunEvent:
    seq: int
    kind: str  # "message" (the agent's or the task's) or "notice" (Certo's own)
    role: str
    text: str
    at: float


@dataclass
class Run:
    id: str
    task: str
    project: str | None
    workspace: str
    state: str = "running"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    result: dict[str, Any] | None = None
    events: list[RunEvent] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # `inconclusive` and `unchanged` count as not passing (--require-verification).
    require_verification: bool = False

    def status(self) -> dict[str, Any]:
        return {
            "run_id": self.id,
            "task": self.task,
            "project": self.project,
            "workspace": self.workspace,
            "state": self.state,
            "verdict": self.result["verdict"] if self.result else None,
            # As `certo`'s exit code 0 says; None until there is a verdict.
            "passed": passes(
                self.result["verdict"] if self.result else None, self.require_verification
            ),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "events": len(self.events),
            "result": self.result,
        }


def _continue(cfg: Config, plan: RunPlan, options: RunOptions) -> tuple[Config, list[str]]:
    """A resume, or a milestone file run again, keeps how the run it
    continues chose its models and its budget, as `certo --resume` does,
    unless `options` choose now. Returns the config and Certo's notes."""
    from .api import continue_budgets, continue_model_selection

    continued = plan.resume_from
    if continued is None and plan.milestones is not None:
        from .project_state import load_record

        continued = load_record(cfg.workspace)
    cfg, mode_note = continue_model_selection(
        cfg,
        continued,
        model_flag=bool(options.model or options.escalate is not None or options.auto_model),
    )
    cfg, budget_note = continue_budgets(
        cfg,
        continued,
        time_flag=options.max_minutes is not None,
        steps_flag=options.max_steps is not None,
    )
    return cfg, [n for n in (mode_note, budget_note) if n]


def _message_text(message: Any) -> str:
    parts = [getattr(c, "text", None) for c in getattr(message, "content", ())]
    return "\n".join(p for p in parts if p)


def _default_stream(task: str, **kwargs: Any) -> Any:
    from .runner import stream_task

    return stream_task(task, **kwargs)


class RunManager:
    """The runs one process started. `load` reads the settings (the caller's
    `load_config`); `stream` runs a task (tests pass a fake)."""

    def __init__(
        self,
        *,
        load: Callable[[], Config],
        stream: Callable[..., Any] = _default_stream,
    ) -> None:
        self._load = load
        self._stream = stream
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._busy: dict[str, str] = {}  # workspace -> id of the run there

    def start(
        self,
        task: str | None,
        options: RunOptions,
        *,
        acceptance_checks: Sequence[Any] | None = None,
        resume: bool = False,
        milestones_file: str | None = None,
        from_milestone: int | None = None,
        make_milestones: bool = False,
        milestone_count: int | None = None,
        require_verification: bool = False,
    ) -> Run:
        """Prepare and start a run; raises `ConfigError` or `UsageError`
        before anything runs, and `NothingToDo` when there's nothing left to
        run. With `resume`, the run continues the project's last run (or its
        milestones), and `task` is an optional extra instruction. With
        `milestones_file`, the task is that file's milestones, from
        milestone `from_milestone` when given. With `make_milestones`, a
        model first splits `task` into milestones, in the run's thread (it
        takes a model call), as `certo --make-milestones` does; with
        `milestone_count` (which turns it on), into exactly that many."""
        cfg = resolve_config(options, load=self._load)
        workspace = os.path.abspath(cfg.workspace)
        planner = None
        if milestone_count is not None:
            from .milestone_planner import MAX_MILESTONE_COUNT, MIN_MILESTONE_COUNT

            if not MIN_MILESTONE_COUNT <= milestone_count <= MAX_MILESTONE_COUNT:
                raise UsageError(
                    f"milestone_count must be from {MIN_MILESTONE_COUNT} to {MAX_MILESTONE_COUNT}"
                )
            make_milestones = True
        if make_milestones:
            planner_cfg, how = self._planner(
                cfg, options, task, resume, milestones_file, from_milestone
            )
            planner = (planner_cfg, how, milestone_count)
        with self._lock:
            other = self._busy.get(workspace)
            if other is not None:
                raise UsageError(
                    f"run {other} is still working in {workspace}: wait for it, or cancel it"
                )
            plan = plan_run(
                cfg,
                task=task,
                resume=resume,
                milestones_file=milestones_file,
                from_project=options.project is not None,
                from_milestone=from_milestone,
            )
            cfg, notes = _continue(cfg, plan, options)
            ladder = load_run_ladder(cfg)
            prepare_workspace(cfg, options)
            if planner is not None:
                shown = f"{task} (milestones planned first)"
            elif plan.resume_from is not None and plan.milestones is None:
                shown = plan.resume_from.task
            elif plan.milestones is not None:
                shown = f"{len(plan.milestones.plan)} milestones from {plan.milestones.source}"
            else:
                shown = task or ""
            run = Run(
                id=uuid.uuid4().hex[:12],
                task=shown,
                project=options.project,
                workspace=workspace,
                require_verification=require_verification,
            )
            self._runs[run.id] = run
            self._busy[workspace] = run.id
        for note in notes:
            self._add_event(run, "notice", "certo", note)
        thread = threading.Thread(
            target=self._work,
            args=(
                run,
                cfg,
                ladder,
                acceptance_checks,
                plan,
                task if resume else None,
                task,
                planner,
            ),
            name=f"certo-run-{run.id}",
            daemon=True,
        )
        thread.start()
        return run

    @staticmethod
    def _planner(
        cfg: Config,
        options: RunOptions,
        task: str | None,
        resume: bool,
        milestones_file: str | None,
        from_milestone: int | None,
    ) -> tuple[Config, str]:
        """`make_milestones`' checks, as the CLI's: the planner's config and
        how it was chosen. Raises `UsageError` or `ConfigError`."""
        from .milestone_planner import choose_planner
        from .milestones import written_in_milestones

        if resume or from_milestone is not None or milestones_file is not None:
            raise UsageError(
                "make_milestones writes a new plan: not with a resume, from_milestone or "
                "a milestones file. To continue a plan it wrote, use run_resume"
            )
        if not task:
            raise UsageError("make_milestones needs a task")
        if written_in_milestones(task):
            raise UsageError("the task is already written in milestones; run it as it is")
        return choose_planner(cfg)

    def _add_event(self, run: Run, kind: str, role: str, text: str) -> None:
        with self._lock:
            run.events.append(
                RunEvent(len(run.events) + 1, kind, role, text[:EVENT_TEXT_CHARS], time.time())
            )

    def _work(
        self,
        run: Run,
        cfg: Config,
        ladder: Any,
        acceptance_checks: Any,
        plan: RunPlan,
        instruction: str | None,
        task: str | None,
        planner: tuple[Config, str, int | None] | None = None,
    ) -> None:
        from .cancel import RunCancelled
        from .milestones import clear_state
        from .runner import TaskResult, is_notice

        messages: list[Any] = []
        notices: list[str] = []  # Certo's, for the result and the report

        def on_message(message: Any) -> None:
            messages.append(message)
            text = _message_text(message)
            if text:
                kind = "notice" if is_notice(message) else "message"
                if kind == "notice":
                    notices.append(text)
                self._add_event(run, kind, str(getattr(message, "role", "")), text)

        started = datetime.now(UTC)
        history = {"task": run.task}

        def record_run(ended: str, outcome: Any = None, summary: Any = None) -> None:
            # In the project's .certo/RUNS.md, as a command-line run is.
            entry = run_entry(cfg, ladder, history["task"], ended, started, outcome, summary)
            entry = replace(entry, report=report_relpath(started))
            try:
                append_run(run.workspace, entry)
            except OSError:
                logger.warning("Could not add run %s to .certo/RUNS.md", run.id, exc_info=True)

        def run_one(text: str, resume: Any, extra: str | None, checks: Any) -> Any:
            messages.clear()
            outcome = self._stream(
                text,
                cfg=cfg,
                on_message=on_message,
                acceptance_checks=checks,
                run_id=run.id,
                project=run.project,
                save_state=True,
                resume_from=resume,
                resume_instruction=extra,
                ladder=ladder,
                cancel=run.cancel_event,
            )
            return TaskResult(list(messages), outcome)

        def say(line: str) -> None:
            self._add_event(run, "notice", "certo", line.strip())

        if planner is not None:
            try:
                plan, task = self._plan_milestones(run, cfg, planner, task or "", say)
            except Exception as exc:  # noqa: BLE001 - kept in the run's result, not raised
                plan = RunPlan()
                say(f"Planning failed ({exc}). The task runs as one, as it is.")
        state = plan.milestones

        def milestones() -> list[dict[str, Any]] | None:
            if state is None:
                return None
            return state.rows()

        def finish(
            ended_as: str, outcome: Any = None, error: str | None = None, summary: Any = None
        ) -> None:
            result = run_result(
                outcome,
                task=run.task,
                workspace=run.workspace,
                project=run.project,
                milestones=milestones(),
                error=error,
                notices=notices,
            )
            try:
                write_report(run.workspace, result, started)
            except OSError:
                logger.warning("Could not write the report of run %s", run.id, exc_info=True)
            if outcome is not None:
                ended = outcome.verification_state
            elif ended_as == "cancelled":
                ended = "interrupted"
            else:
                lines = (error or "").strip().splitlines()
                ended = "error: " + (lines[0][:100] if lines else "")
            # Milestones add one entry each as they end.
            if state is None or outcome is None:
                record_run(ended, outcome, summary)
            with self._lock:
                run.state = ended_as
                run.result = result
                run.ended_at = time.time()
                self._busy.pop(run.workspace, None)

        try:
            if state is not None:
                outcome = run_milestones(
                    state,
                    cfg,
                    run_one,
                    say=say,
                    resume_from=plan.resume_from,
                    restart=plan.restart,
                    instruction=instruction,
                    acceptance_checks=acceptance_checks,
                    history=history,
                    record_run=record_run,
                )
            else:
                if plan.resume_from is None:
                    clear_state(cfg.workspace)  # a new task here isn't the old milestones
                text = plan.resume_from.task if plan.resume_from is not None else task or ""
                outcome = run_one(text, plan.resume_from, instruction, acceptance_checks).outcome
        except RunCancelled as exc:
            finish("cancelled", error="cancelled", summary=getattr(exc, "run_summary", None))
        except Exception as exc:  # noqa: BLE001 - kept in the run's result, not raised
            finish(
                "error",
                error=str(exc) or type(exc).__name__,
                summary=getattr(exc, "run_summary", None),
            )
        else:
            finish("finished", outcome)

    def _plan_milestones(
        self,
        run: Run,
        cfg: Config,
        planner: tuple[Config, str, int | None],
        task: str,
        say: Callable[[str], None],
    ) -> tuple[RunPlan, str]:
        """`make_milestones`: the planner's plan, saved as the project's
        `.certo/milestones.md` and read as a milestones file; or no plan
        (the task runs as one) when the planner kept it as one."""
        from .milestone_planner import plan_milestones, save_plan
        from .milestones import clear_state

        planner_cfg, how, count = planner
        say(f"Planning milestones with {planner_cfg.model} ({how})...")
        planned = plan_milestones(task, planner_cfg, count=count)
        if planned.text is None:
            say(f"Certo: {planned.reason}. The task runs as one, as it is.")
            return RunPlan(), task
        if planned.note:
            say(f"Certo: {planned.note}.")
        path = save_plan(cfg.workspace, planned.text)
        cost = f", ${planned.cost:.4f}" if planned.cost else ""
        titles = "\n".join(f"  {n}. {t}" for n, t in enumerate(planned.titles, start=1))
        say(
            f"Plan: {len(planned.titles)} milestones, written by {planned.model} in "
            f"{planned.seconds:.0f}s{cost}. Saved as {path}\n{titles}"
        )
        clear_state(cfg.workspace)  # a new plan: its milestones start from 1
        plan = plan_run(cfg, task=planned.text, milestones_file=path)
        with self._lock:
            run.task = f"{len(planned.titles)} milestones from {path}"
        return plan, planned.text

    def start_verify(
        self,
        options: RunOptions,
        *,
        verify: Callable[[str], Any] | None = None,
        require_verification: bool = False,
    ) -> Run:
        """Run Certo's checks on a folder without an agent, as `certo verify`
        does, as a run: its result has the verdict and the checks. It can't be
        cancelled; each check has its own time limit."""
        cfg = resolve_config(options, load=self._load)
        workspace = os.path.abspath(cfg.workspace)
        if not os.path.isdir(workspace):
            raise UsageError(f"{workspace} doesn't exist")
        with self._lock:
            other = self._busy.get(workspace)
            if other is not None:
                raise UsageError(
                    f"run {other} is still working in {workspace}: wait for it, or cancel it"
                )
            run = Run(
                id=uuid.uuid4().hex[:12],
                task="certo verify",
                project=options.project,
                workspace=workspace,
                require_verification=require_verification,
            )
            self._runs[run.id] = run
            self._busy[workspace] = run.id
        threading.Thread(
            target=self._verify_work, args=(run, verify), name=f"certo-run-{run.id}", daemon=True
        ).start()
        return run

    def _verify_work(self, run: Run, verify: Callable[[str], Any] | None) -> None:
        from .result import check_dict
        from .verification import _build_completion_contract, run_full_verification

        result = run_result(None, task=run.task, workspace=run.workspace, project=run.project)
        try:
            found = (verify or run_full_verification)(run.workspace)
        except Exception as exc:  # noqa: BLE001 - kept in the run's result, not raised
            state = "error"
            result["error"] = str(exc) or type(exc).__name__
        else:
            state = "finished"
            for notice in found.notices:
                self._add_event(run, "notice", "certo", notice)
            for check in found.checks:
                self._add_event(run, "notice", "certo", f"{check.status} {check.name}")
            contract = _build_completion_contract(
                "certo verify", found, skipped=False, aborted=False
            )
            result.update(
                verdict=found.state,
                limitations=list(contract.limitations),
                checks=[check_dict(c) for c in found.checks],
            )
        with self._lock:
            run.state = state
            run.result = result
            run.ended_at = time.time()
            self._busy.pop(run.workspace, None)

    def busy(self, workspace: str) -> str | None:
        """The id of the run working in `workspace`, or None."""
        with self._lock:
            return self._busy.get(os.path.abspath(workspace))

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise UnknownRun(f"no run with id {run_id!r}")
        return run

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        with self._lock:
            return run.status()

    def events(self, run_id: str, since: int = 0) -> dict[str, Any]:
        """The events after number `since`, at most `EVENTS_PER_CALL`, and the
        cursor to pass next time."""
        run = self.get(run_id)
        with self._lock:
            chunk = run.events[since : since + EVENTS_PER_CALL]
            state = run.state
        return {
            "run_id": run_id,
            "state": state,
            "events": [
                {"seq": e.seq, "kind": e.kind, "role": e.role, "text": e.text, "at": e.at}
                for e in chunk
            ],
            "next": since + len(chunk),
        }

    def cancel(self, run_id: str) -> dict[str, Any]:
        """Ask a running run to stop at its next step. A run that already
        ended stays as it was."""
        run = self.get(run_id)
        run.cancel_event.set()
        return self.status(run_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {k: v for k, v in r.status().items() if k != "result"} for r in self._runs.values()
            ]
