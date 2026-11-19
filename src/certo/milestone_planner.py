"""`certo --make-milestones`: before the run, a model rewrites a task with
no milestones as a milestone task, which then runs as `--milestones` does.

The planner writes only the milestone sections (`## Milestone N: title`,
what to build, how to tell it is done). The file Certo saves,
`.certo/milestones.md` in the project, is the task as the user wrote it
followed by those sections: the task is the context every milestone gets,
so no requirement is lost in the rewrite, and the user can edit the file
and run it again with `certo --milestones .certo/milestones.md`. The plan
is parsed with the milestone parser before use. A plan that can't be read,
a model that fails, or a planner that answers one milestone leaves the
task to run as one, as it is. Acceptance blocks the planner writes are
taken out: its checks could be wrong, and aren't measured yet.

The planner model (DECISIONS.md, 2026-11-16): `CERTO_PLANNER_MODEL`, a
model in `models.yaml`; else, when the run already lets Certo choose its
models (`--auto-model`, `--escalate`), the first model of the `planning`
task profile; else the run's own model. Never a model named in code.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import Config
from .milestones import MilestoneError, _take_acceptance, parse_milestones
from .project_state import ensure_state_dir

PLAN_FILE = "milestones.md"
PLANNING_PROFILE = "planning"
MAX_MILESTONES = 8
ONE_MILESTONE = "ONE MILESTONE"

PROMPT = """You plan software work for a coding agent. Split the task below \
into milestones that the agent builds one after another, each in its own \
session. After each milestone the project's own checks (its tests, its \
build) are run before the next one starts.

Rules:
- Start each milestone with a level-2 heading `## Milestone N: short title`, \
N from 1, then a few short lines: what to build in this milestone, and how \
to tell it is done (what a test or a run of the program shows).
- The first milestone sets up the project and its tests. Every milestone \
leaves the project working and its tests passing.
- Keep to the task: add no feature, tool, library or file it doesn't ask \
for, and leave none of its requirements out. Each requirement belongs to \
one milestone.
- Between 2 and {max} milestones; fewer for a smaller task. If the task is \
small enough to build and check in one go, answer only: {one}
- Write nothing before the first heading and nothing after the last \
milestone. No code.

The task:

<task>
{task}
</task>
"""

# A milestone heading, as the milestone parser reads it (milestones._HEADING).
_FIRST_HEADING = re.compile(r"^##\s+(milestone\s+|m)\d+\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class PlannedTask:
    """What the planner gave: `text`, the milestone task to save and run,
    or None with `reason`, why the task runs as one."""

    text: str | None
    reason: str
    model: str
    seconds: float = 0.0
    cost: float = 0.0
    titles: tuple[str, ...] = ()


# (planner config, prompt) -> (reply text, cost in US dollars)
Complete = Callable[[Config, str], tuple[str, float]]


def _complete(cfg: Config, prompt: str) -> tuple[str, float]:
    from .llm import complete_once

    return complete_once(cfg, prompt, usage_id="planner")


def milestone_sections(reply: str) -> str | None:
    """The milestone sections of a planner's reply, without anything
    before the first heading, an enclosing code fence or acceptance
    blocks; None when the reply has no milestone heading."""
    text = reply.strip()
    fenced = re.fullmatch(r"(```+|~~~+)[^\n]*\n(.*?)\n?\1\s*", text, re.DOTALL)
    if fenced:
        text = fenced.group(2)
    first = _FIRST_HEADING.search(text)
    if first is None:
        return None
    text, _blocks = _take_acceptance(text[first.start() :])
    return text.strip()


def assemble(task: str, sections: str) -> str:
    """The milestone task: the user's task as written, then the plan."""
    return f"{task.rstrip()}\n\n{sections.strip()}\n"


def plan_milestones(task: str, cfg: Config, complete: Complete | None = None) -> PlannedTask:
    """Ask `cfg`'s model for a milestone plan of `task`. Never raises for a
    model's failure or a plan that can't be used: the result then says why
    the task runs as one."""
    started = time.monotonic()
    prompt = PROMPT.format(task=task.strip(), max=MAX_MILESTONES, one=ONE_MILESTONE)
    try:
        reply, cost = (complete or _complete)(cfg, prompt)
    except Exception as exc:  # noqa: BLE001 - reported, the run goes on as one task
        reason = f"the planner ({cfg.model}) failed: {type(exc).__name__}: {exc}"
        return PlannedTask(None, _one_line(reason), cfg.model, time.monotonic() - started)
    seconds = time.monotonic() - started

    def one_task(reason: str) -> PlannedTask:
        return PlannedTask(None, reason, cfg.model, seconds, cost)

    if reply.strip().upper().startswith(ONE_MILESTONE):
        return one_task("the planner kept it as one milestone: small enough to build in one go")
    sections = milestone_sections(reply)
    if sections is None:
        return one_task("the planner's answer had no milestone headings")
    text = assemble(task, sections)
    try:
        plan = parse_milestones(text)
    except MilestoneError as exc:
        return one_task(f"the plan couldn't be read ({exc})")
    if len(plan) < 2:
        return one_task("the planner wrote one milestone: small enough to build in one go")
    if len(plan) > MAX_MILESTONES:
        return one_task(f"the planner wrote {len(plan)} milestones, more than {MAX_MILESTONES}")
    titles = tuple(m.label for m in plan.milestones)
    return PlannedTask(text, "", cfg.model, seconds, cost, titles)


def _one_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plan_path(workspace: str) -> str:
    return os.path.join(os.path.abspath(workspace), ".certo", PLAN_FILE)


def save_plan(workspace: str, text: str) -> str:
    """Write the milestone task to `.certo/milestones.md`; return its path."""
    ensure_state_dir(workspace)
    path = plan_path(workspace)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def choose_planner(cfg: Config) -> tuple[Config, str]:
    """The config to plan with, and how it was chosen. Raises ConfigError
    when `CERTO_PLANNER_MODEL` names a model `models.yaml` doesn't enable,
    or the model files can't be read for it."""
    if not cfg.planner_model and cfg.model_selection not in ("auto", "escalate"):
        return cfg, "the run's model"
    from .catalog_check import load_checked_catalog
    from .model_catalog import ModelCatalogError, rank_for_profile
    from .model_selection import config_for_entry, config_for_named_model

    if cfg.planner_model:
        return config_for_named_model(cfg, cfg.planner_model, "CERTO_PLANNER_MODEL"), (
            "CERTO_PLANNER_MODEL"
        )
    try:
        catalog = load_checked_catalog(
            cfg.models_file,
            cfg.models_list_file,
            task_profiles_file=cfg.task_profiles_file,
            escalation_file=cfg.escalation_file,
            mode="auto",
            project_dir=cfg.workspace,
        )
    except ModelCatalogError:
        return cfg, "the run's model (the model files couldn't be read)"
    profile = next((p for p in catalog.task_profiles if p.name == PLANNING_PROFILE), None)
    if profile is None:
        return cfg, f"the run's model (no '{PLANNING_PROFILE}' task profile)"
    from .model_reachability import unreachable_reason

    ranked, _how = rank_for_profile(catalog, profile)
    for entry in ranked:
        # A local model whose server is off is passed over, as --auto-model does.
        if unreachable_reason(entry) is None:
            return config_for_entry(cfg, entry), f"the '{PLANNING_PROFILE}' task profile"
    return cfg, "the run's model (no model of the planning profile can be reached)"
