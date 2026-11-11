"""The shared core under Certo's interfaces: the command line, `certo-server`
and the MCP server call these functions instead of each building a run its own
way (DECISIONS.md, "The MCP server: every command, on a shared core").

Nothing here prints or asks: problems are raised as `ConfigError` (a setting
or a file is wrong) or `UsageError` (the options don't go together), with a
message the interface shows as it is. Options are named the way each interface
spells them through `spell`, so the command line says `--model` and the server
says `model`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .config import (
    Config,
    ConfigError,
    defer_llm_check,
    ensure_llm_configured,
    override_llm,
    resolve_project_dir,
)
from .escalation import ResolvedLadder, load_ladder

if TYPE_CHECKING:
    from .milestones import MilestoneState

Spell = Callable[[str], str]


class UsageError(ValueError):
    """Options that don't go together. The message is user-facing."""


def _plain(name: str) -> str:
    return name


@dataclass(frozen=True)
class RunOptions:
    """What a caller asks for, before any setting is read.

    `escalate` is None for no ladder, "" for the default ladder, or a ladder's
    name. `independent_tests` None keeps the setting; True or False sets it.
    `workspace` is a folder to work in instead of `CERTO_WORKSPACE`; the
    caller checks it's one it may use. It can't go with `project`.
    """

    project: str | None = None
    workspace: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    escalate: str | None = None
    auto_model: bool = False
    execution: str | None = None
    interactive: bool = False
    independent_tests: bool | None = None
    independent_tests_strict: bool = False
    verbose: bool = False
    agents_md: str | None = None
    max_steps: int | None = None
    max_minutes: int | None = None


def resolve_config(
    options: RunOptions,
    *,
    load: Callable[[], Config],
    spell: Spell = _plain,
) -> Config:
    """The settings a run uses: `load()` (the settings files and environment),
    then `options` on top. The project folder is resolved but not created:
    `prepare_workspace` does that, once every check that can refuse is done."""
    if options.project is not None and options.workspace is not None:
        raise UsageError(f"give {spell('project')} or {spell('folder')}, not both")
    if options.agents_md is not None and options.project is None:
        raise UsageError(f"{spell('agents_md')} requires {spell('project')}")
    if options.escalate is not None and (options.auto_model or options.model is not None):
        others = spell("model")
        if options.auto_model:
            others = f"{spell('auto_model')} or {others}"
        raise UsageError(
            f"{spell('escalate')} can't be combined with {others}: the ladder decides which "
            "models run"
        )

    # The overrides go on before the required-field checks, so they alone
    # can satisfy them (issue #11).
    with defer_llm_check():
        cfg = load()
    if (
        options.model is not None
        or options.api_key is not None
        or options.base_url is not None
        or options.reasoning_effort is not None
    ):
        cfg = override_llm(
            cfg,
            model=options.model,
            api_key=options.api_key,
            base_url=options.base_url,
            reasoning_effort=options.reasoning_effort,
        )
    # With a ladder or --auto-model the model files name every model and its
    # key, so CERTO_LLM_MODEL isn't needed (DECISIONS.md).
    if options.escalate is None and not options.auto_model and cfg.model_selection == "manual":
        cfg = ensure_llm_configured(cfg)

    if options.execution is not None:
        cfg = replace(cfg, execution=options.execution)
    if options.interactive:
        cfg = replace(cfg, interactive=True)
    if options.independent_tests is not None:
        cfg = replace(cfg, independent_tests=options.independent_tests)
        if not options.independent_tests:
            cfg = replace(cfg, independent_tests_strict=False)
    if options.independent_tests_strict:
        cfg = replace(cfg, independent_tests=True, independent_tests_strict=True)
    if options.verbose:
        cfg = replace(cfg, verbose=True)
    if options.max_steps is not None:
        if options.max_steps < 1:
            raise UsageError(f"{spell('max_steps')} must be 1 or more")
        cfg = replace(cfg, max_iterations=options.max_steps)
    if options.max_minutes is not None:
        if options.max_minutes < 1:
            raise UsageError(f"{spell('max_time')} must be 1 or more (minutes)")
        cfg = replace(cfg, max_task_seconds=options.max_minutes * 60)

    if options.escalate is not None:
        cfg = replace(cfg, model_selection="escalate", escalation_ladder=options.escalate)
    elif options.auto_model:
        cfg = replace(cfg, model_selection="auto")
    elif cfg.model_selection == "escalate" and options.model is not None:
        raise UsageError(
            f"{spell('model')} can't be used while CERTO_MODEL_SELECTION=escalate: the "
            "ladder decides which models run"
        )

    if options.project is not None:
        cfg = replace(cfg, workspace=resolve_project_dir(cfg.projects_dir, options.project))
    elif options.workspace is not None:
        cfg = replace(cfg, workspace=options.workspace)
    return cfg


def load_run_ladder(
    cfg: Config, on_warning: Callable[[str], None] | None = None
) -> ResolvedLadder | None:
    """The ladder an escalation climbs, or None when `cfg` doesn't escalate.
    With --auto-model, checks the model files the same way, so a broken file
    is refused before the run starts."""
    if cfg.model_selection == "escalate":
        return load_ladder(
            cfg.models_file,
            cfg.models_list_file,
            cfg.escalation_ladder or None,
            escalation_file=cfg.escalation_file,
            task_profiles_file=cfg.task_profiles_file,
            on_warning=on_warning,
        )
    if cfg.model_selection == "auto":
        from .catalog_check import load_checked_catalog
        from .model_catalog import ModelCatalogError
        from .model_files import resolve_optional
        from .profile_choice import NO_PROFILES

        # Without task profiles every model ranks the same and the first in
        # models_list.yaml would go first: refused (DECISIONS.md, 2026-11-11).
        catalog = load_checked_catalog(
            cfg.models_file,
            cfg.models_list_file,
            task_profiles_file=cfg.task_profiles_file,
            escalation_file=cfg.escalation_file,
            mode="auto",
        )
        profiles_path, _ = resolve_optional(cfg.task_profiles_file, cfg.escalation_file)
        if profiles_path is None:
            raise ModelCatalogError(NO_PROFILES)
        if not catalog.task_profiles:
            raise ModelCatalogError(f"{profiles_path} has no task profile. {NO_PROFILES}")
    return None


def prepare_workspace(cfg: Config, options: RunOptions) -> bool:
    """Make the project folder ready for a run: refuse OpenHands plugins from
    outside it (plugins.py), create a named project and remember that Certo
    created it, and write `agents_md`. Returns whether the folder was created
    now."""
    if cfg.execution == "local":
        from .plugins import foreign_plugins, refusal

        found = foreign_plugins(cfg.workspace, cfg.projects_dir)
        if found:
            raise ConfigError(refusal(found))
    created = False
    if options.project is not None:
        from .worktree import record_created_project

        created = not os.path.exists(cfg.workspace)
        os.makedirs(cfg.workspace, exist_ok=True)
        if created:
            record_created_project(cfg.projects_dir, options.project)
    if options.agents_md is not None:
        from .skills import write_project_context

        write_project_context(cfg.workspace, options.agents_md)
    return created


class NothingToDo(Exception):
    """The request needs no run: every milestone, or the last run, is already
    `verified`. The message says so, and isn't an error."""


@dataclass(frozen=True)
class RunPlan:
    """What a run continues: a saved run (`resume_from`), a plan of
    milestones, or a milestone a ladder starts again (`restart`)."""

    resume_from: Any = None
    milestones: Any = None
    restart: Any = None
    # What the caller shows before the run: where a milestone run starts.
    note: str | None = None


def _continue_milestones(
    state: Any,
    saved: Any,
    text: str,
    workspace: str,
    from_milestone: int | None,
    spell: Spell,
) -> RunPlan:
    """A new run of a milestones file: it goes on from where an earlier run
    of the same, unedited file stopped (2026-11-10: running the file again
    started over from milestone 1 and wiped the verdicts), or from
    `from_milestone`. The milestone it starts at gets a fresh conversation,
    told how its last try ended, when the last run was that milestone's."""
    from .milestones import is_milestone_task
    from .project_state import load_record

    total = len(state.plan)
    same = state.continue_from(saved, text)
    if from_milestone is not None:
        if not 1 <= from_milestone <= total:
            raise UsageError(
                f"{spell('from_milestone')} must be between 1 and {total}, the "
                "milestones' numbers as Certo shows them (Milestone N of "
                f"{total})"
            )
        state.verdicts = {n: v for n, v in state.verdicts.items() if n < from_milestone}
        state.start = from_milestone
        note = f"Milestones: starting at {from_milestone} of {total}, as asked."
    elif same:
        number = state.next_number()
        if number is None:
            raise NothingToDo(
                f"All {total} milestones of {saved.source} are already 'verified' here. "
                f"To run them again: {spell('from_milestone')} 1."
            )
        done = [n for n in range(1, number) if state.verdicts.get(n) == "verified"]
        if not done:
            return RunPlan(milestones=state)
        shown = f"1 to {done[-1]}" if len(done) > 1 else str(done[0])
        note = (
            f"Milestones: {shown} of {total} already verified here (.certo/milestones.json); "
            f"starting at {number}: {state.plan.get(number).label}. "
            f"To start again: {spell('from_milestone')} 1."
        )
    elif saved is not None and saved.source == state.source:
        note = (
            "Milestones: the task file changed since its last run here, so they start "
            f"from 1. To skip some: {spell('from_milestone')} N."
        )
    else:
        return RunPlan(milestones=state)
    number = state.next_number()
    record = load_record(workspace)
    restart = (
        record
        if number is not None
        and record is not None
        and record.verdict != "verified"
        and is_milestone_task(record.task, state.plan, number)
        else None
    )
    return RunPlan(milestones=state, restart=restart, note=note)


def plan_run(
    cfg: Config,
    *,
    task: str | None,
    resume: bool = False,
    milestones_file: str | None = None,
    from_project: bool = False,
    want_milestones: bool = False,
    from_milestone: int | None = None,
    spell: Spell = _plain,
) -> RunPlan:
    """Read what a run continues from the project's `.certo/` folder (with
    `resume`) or from a milestones task file. Raises `UsageError` when
    there's nothing to continue or the file can't be used, and
    `NothingToDo` when it's all `verified` already. `task` is the task or,
    on a resume, the extra instruction."""
    from .milestones import MilestoneError, MilestoneState, is_milestone_task, reopen
    from .milestones import load_state as load_milestones
    from .project_state import load_record

    workspace = os.path.abspath(cfg.workspace)
    if resume and from_project and not os.path.isdir(cfg.workspace):
        raise UsageError(f"nothing to resume: {cfg.workspace} doesn't exist.")
    saved = load_milestones(cfg.workspace) if resume else None
    # Milestones restart a milestone on the ladder's first rung; a single
    # run's resume can't climb.
    if cfg.model_selection == "escalate" and resume and saved is None:
        raise UsageError(
            "--resume can't be combined with escalation. Resume continues one "
            "model's conversation; run it without --escalate (after --milestones, it "
            "can)."
        )
    if milestones_file is not None:
        # A file, not text or a URL: a resume reads it again.
        if not os.path.isfile(milestones_file):
            raise UsageError(f"--milestones needs a task file; {milestones_file!r} isn't one.")
        try:
            with open(milestones_file, encoding="utf-8") as f:
                text = f.read()
            state = MilestoneState.from_text(text, milestones_file)
        except MilestoneError as exc:
            raise UsageError(f"{milestones_file}: {exc}") from exc
        return _continue_milestones(
            state, load_milestones(cfg.workspace), text, cfg.workspace, from_milestone, spell
        )
    if from_milestone is not None:
        raise UsageError(
            f"{spell('from_milestone')} needs a task file in milestones, run without "
            f"{spell('resume')}"
        )
    if resume and saved is None and want_milestones:
        raise UsageError(
            f"no milestones to resume in {workspace}: Certo "
            "keeps them in .certo/milestones.json, and there is none here."
        )
    if saved is not None:
        if saved.next_number() is None:
            raise NothingToDo(
                f"All {len(saved.titles)} milestones here are already "
                "'verified'. For more work, run a new task: certo \"...\""
            )
        try:
            state = reopen(saved)
        except MilestoneError as exc:
            raise UsageError(str(exc)) from exc
        number = state.next_number()
        record = load_record(cfg.workspace)
        # The saved run continues only if it was this milestone's: otherwise
        # (stopped before it began) the milestone starts afresh.
        if record is not None and is_milestone_task(record.task, state.plan, number):
            if cfg.model_selection == "escalate":
                # A ladder starts the milestone again on its first rung, in
                # a fresh conversation told how the last try ended.
                return RunPlan(milestones=state, restart=record)
            return RunPlan(milestones=state, resume_from=record)
        return RunPlan(milestones=state)
    if resume:
        record = load_record(cfg.workspace)
        if record is None:
            raise UsageError(
                f"nothing to resume in {workspace}: Certo keeps "
                "the last run's state in .certo/, and there is none here (or it can't "
                "be read). Run a task first."
            )
        if record.verdict == "verified" and task is None and not record.cut_short:
            raise NothingToDo(
                "The last run here already ended with 'verified'. To continue anyway, "
                'say what to do next: certo --resume "..."'
            )
        return RunPlan(resume_from=record)
    return RunPlan()


def run_milestones(
    state: MilestoneState,
    cfg: Config,
    run_one: Callable[..., Any],
    *,
    say: Callable[[str], None],
    resume_from: Any,
    restart: Any = None,
    instruction: str | None,
    acceptance_checks: Any,
    history: dict,
    record_run: Callable[..., None],
) -> Any:
    """Milestone mode: run each milestone not yet verified, in order, each
    in its own conversation, and stop at the first that isn't `verified`.
    Returns the last milestone's outcome with the run summary and the
    rungs of all of them. `.certo/milestones.json` records each verdict as it comes.
    `say` gets each line to show (a terminal prints them; the MCP server keeps
    them as notices). `run_one(text, resume, instruction, checks)` runs one
    milestone and returns what `run_task` returns."""
    from .escalation import format_rung_lines
    from .milestones import checks_up_to, handover, milestone_task, summary_lines
    from .milestones import save_state as save_milestones
    from .project_state import ensure_state_dir, load_record, render_status, save_record
    from .run_summary import combine_summaries
    from .checkpoints import safe_snapshot

    workspace = cfg.workspace
    ensure_state_dir(workspace)
    total = len(state.plan)
    summaries = []
    ran = []  # every milestone's rungs: the final outcome has only the last one's
    number = state.next_number()
    outcome = None
    first = True
    # What the milestone before left; a resume past milestone 1 has only
    # the folder, its conversation was in an earlier session.
    left = handover(workspace, [], number - 1) if number is not None and number > 1 else None
    while number is not None:
        milestone = state.plan.get(number)
        state.current = number
        save_milestones(workspace, state)
        say(f"\nMilestone {number} of {total}: {milestone.label}")
        if cfg.checkpoints:
            safe_snapshot(workspace, f"before milestone {number}", always=True)
        text = milestone_task(state.plan, number, left)
        resume = resume_from if first else None
        extra = instruction if first else None
        if first and restart is not None:
            text += (
                "\n\nAn earlier try at this milestone didn't pass. Certo's record of how "
                "it ended is below; the files it left are in the folder.\n\n"
                + render_status(restart)
            )
        if extra and resume is None:
            text += f"\n\nAdditional instruction from the user:\n{extra.strip()}"
            extra = None
        checks = checks_up_to(state.plan, number)
        if number == total and acceptance_checks:
            checks += list(acceptance_checks)
        history["task"] = f"Milestone {number} of {total}: {milestone.label}"
        result = run_one(text, resume, extra, checks or None)
        outcome = result.outcome
        if outcome.run_summary is not None:
            summaries.append(outcome.run_summary)
        state.verdicts[number] = outcome.verification_state
        state.skills[number] = outcome.skills_used
        if outcome.run_summary is not None:
            state.usage[number] = outcome.run_summary
        save_milestones(workspace, state)
        record = load_record(workspace)
        if record is not None:  # STATUS.md shows the new verdict in its list
            try:
                save_record(workspace, record)
            except OSError:
                pass
        record_run(outcome.verification_state, outcome)
        say(f"Milestone {number} of {total}: {outcome.verification_state}")
        if outcome.rungs:
            for line in format_rung_lines(outcome.rungs, outcome.final_rung):
                say(f"  {line}")
            ran.extend(outcome.rungs)
        if outcome.independent_tests is not None:
            from .independent_tests import report_line

            say(report_line(outcome.independent_tests, strict=cfg.independent_tests_strict))
        if outcome.verification_state != "verified":
            break
        left = handover(workspace, result, number)
        number = state.next_number()
        first = False
    say("\nMilestones:")
    for line in summary_lines(state):
        say(f"  {line}")
    if summaries:
        outcome = replace(outcome, run_summary=combine_summaries(summaries))
    if ran:
        outcome = replace(outcome, rungs=tuple(ran))
    return outcome
