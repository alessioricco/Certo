"""Read and validate a benchmark file (`bench.yaml`).

The file says which tasks to run, how many times, and which arms to
compare. Each arm names a strategy (see bench_strategies.py) and the
`models.yaml` entries it uses, by catalog name: credentials stay in
`models.yaml`, and `.env` is never read. `activated: false` means Certo
never uses a model, here as everywhere: an arm naming one is an error.
`--auto-model` ranking doesn't apply. No SDK import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .context_window import MIN_CONTEXT_TOKENS
from .bench_strategies import STRATEGIES, BenchConfigError
from .bench_tasks import BUILTIN_TASKS_DIR, BenchTask, BenchTaskError, load_tasks
from .catalog_check import load_checked_catalog
from .model_catalog import (
    LIST_FILE,
    MODELS_FILE,
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogError,
)
from .model_files import example_path, find, missing_message
from .skill_library import official_skills

DEFAULT_BENCH_FILE = "bench.yaml"
_TOP_LEVEL_KEYS = {
    "tasks",
    "repeats",
    "arms",
    "models_file",
    "models_list_file",
    "escalation_file",
    "task_profiles_file",
    "tasks_dir",
}
# Arm names become file names in the results folder.
_ARM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

__all__ = ["Arm", "BenchConfig", "BenchConfigError", "load_bench_config"]


@dataclass(frozen=True)
class Arm:
    name: str
    strategy: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def models(self) -> list[str]:
        return STRATEGIES[self.strategy].models(self.params)


@dataclass(frozen=True)
class BenchConfig:
    path: str
    tasks_dir: str
    tasks: list[BenchTask]
    repeats: int
    arms: list[Arm]
    models_file: str
    catalog: dict[str, ModelCatalogEntry]
    models_list_file: str = ""
    # escalation.yaml, when there is one: cost_axis and max_rungs for the
    # derived ladders of `escalate` arms.
    escalation_file: str = ""
    # task_profiles.yaml, when there is one: only `auto` arms use it.
    task_profiles_file: str = ""
    # models.yaml warnings (catalog_check.py), printed with the plan.
    catalog_warnings: list[str] = field(default_factory=list)
    # The whole catalog (task profiles, escalation settings), for ladders.
    model_catalog: ModelCatalog | None = None

    def fingerprint(self) -> dict[str, Any]:
        """What must match for `--resume` to continue an earlier run."""
        return {
            "tasks": [t.name for t in self.tasks],
            "repeats": self.repeats,
            "arms": [{"name": a.name, "strategy": a.strategy, **a.params} for a in self.arms],
            "arm_models": {a.name: a.models for a in self.arms},
            "models": {name: self.catalog[name].model for a in self.arms for name in a.models},
        }


# Options every arm may have, whatever its strategy (bench_strategies.arm_config).
# Each is kept out of params at its default, so results folders from before
# it still match on --resume.
_ARM_OPTIONS = (
    "independent_tests",
    "condense",
    "context_tokens",
    "max_task_seconds",
    "tool_call_reminders",
    "skills_off",
    "milestones",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BenchConfigError(
            f"benchmark file not found: {path}. Certo ships an example to start from; "
            f"copy it and name the models to compare:\n  cp {example_path('bench.yaml')} {path}"
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BenchConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise BenchConfigError(f"{path} must contain a mapping (tasks, repeats, arms).")
    unknown = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown:
        raise BenchConfigError(
            f"{path}: unknown key(s) {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(_TOP_LEVEL_KEYS))}."
        )
    return raw


def _tasks(raw: Any, available: list[BenchTask], where: str) -> list[BenchTask]:
    by_name = {t.name: t for t in available}
    if raw is None or raw == "all":
        return list(available)
    if not isinstance(raw, list) or not raw or not all(isinstance(n, str) for n in raw):
        raise BenchConfigError(f"{where}: 'tasks' must be 'all' or a list of task names.")
    unknown = [n for n in raw if n not in by_name]
    if unknown:
        raise BenchConfigError(
            f"{where}: unknown task(s) {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(by_name))}."
        )
    if len(set(raw)) != len(raw):
        raise BenchConfigError(f"{where}: a task is listed twice.")
    return [by_name[n] for n in raw]


def _repeats(raw: Any, where: str) -> int:
    if raw is None:
        return 1
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise BenchConfigError(f"{where}: 'repeats' must be a whole number of at least 1.")
    return raw


def _arms(raw: Any, catalog: dict[str, ModelCatalogEntry], where: str) -> list[Arm]:
    if not isinstance(raw, list) or not raw:
        raise BenchConfigError(f"{where}: 'arms' must be a non-empty list.")
    arms: list[Arm] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BenchConfigError(f"{where}: arm {i} must be a mapping.")
        name = item.get("name")
        if not isinstance(name, str) or not _ARM_NAME.match(name):
            raise BenchConfigError(
                f"{where}: arm {i} needs a 'name' made of letters, digits, '.', '_' or '-'."
            )
        if any(a.name == name for a in arms):
            raise BenchConfigError(f"{where}: two arms are named {name!r}.")
        arm_where = f"{where}: arm {name!r}"
        strategy = item.get("strategy")
        if strategy not in STRATEGIES:
            known = ", ".join(sorted(STRATEGIES))
            raise BenchConfigError(
                f"{arm_where}: unknown strategy {strategy!r}. Known strategies: {known}."
            )
        # For every strategy. Kept out of params unless on, so results
        # folders from before it still match on --resume.
        independent = item.get("independent_tests", False)
        if not isinstance(independent, bool):
            raise BenchConfigError(f"{arm_where}: 'independent_tests' must be true or false.")
        condense = item.get("condense", True)
        if not isinstance(condense, bool):
            raise BenchConfigError(f"{arm_where}: 'condense' must be true or false.")
        context = item.get("context_tokens")
        if context is not None:
            if isinstance(context, bool) or not isinstance(context, int):
                raise BenchConfigError(f"{arm_where}: 'context_tokens' must be a whole number.")
            if context < MIN_CONTEXT_TOKENS:
                raise BenchConfigError(
                    f"{arm_where}: 'context_tokens' must be at least {MIN_CONTEXT_TOKENS:,}."
                )
            if strategy != "single":
                raise BenchConfigError(
                    f"{arm_where}: 'context_tokens' works with strategy 'single' only (a "
                    "ladder's models take theirs from models.yaml)."
                )
        budget = item.get("max_task_seconds")
        if budget is not None and (
            isinstance(budget, bool) or not isinstance(budget, int) or budget < 1
        ):
            raise BenchConfigError(
                f"{arm_where}: 'max_task_seconds' must be a whole number of seconds, at least 1."
            )
        reminders = item.get("tool_call_reminders")
        if reminders is not None and (
            isinstance(reminders, bool) or not isinstance(reminders, int) or reminders < 0
        ):
            raise BenchConfigError(
                f"{arm_where}: 'tool_call_reminders' must be a whole number, at least 0."
            )
        skills_off = _skills_off(item.get("skills_off"), arm_where)
        milestones = item.get("milestones", False)
        if not isinstance(milestones, bool):
            raise BenchConfigError(f"{arm_where}: 'milestones' must be true or false.")
        rest = {k: v for k, v in item.items() if k not in _ARM_OPTIONS}
        params = STRATEGIES[strategy].parse(rest, catalog, arm_where)
        if independent:
            params["independent_tests"] = True
        if not condense:
            params["condense"] = False
        if context is not None:
            params["context_tokens"] = context
        if budget is not None:
            params["max_task_seconds"] = budget
        if reminders is not None:
            params["tool_call_reminders"] = reminders
        if skills_off:
            params["skills_off"] = skills_off
        if milestones:
            params["milestones"] = True
        arms.append(Arm(name=name, strategy=strategy, params=params))
    return arms


def _check_milestone_tasks(arms: list[Arm], tasks: list[BenchTask], where: str) -> None:
    """An arm with `milestones: true` needs tasks written in milestones,
    and each such task must be readable: checked before any run starts."""
    from .milestones import MilestoneError, parse_milestones

    if not any(arm.params.get("milestones") for arm in arms):
        return
    for task in tasks:
        try:
            parse_milestones(task.prompt)
        except MilestoneError as exc:
            raise BenchConfigError(
                f"{where}: an arm has 'milestones: true', but task {task.name!r} can't be "
                f"run in milestones: {exc}"
            ) from exc


def _skills_off(raw: Any, where: str) -> list[str]:
    """An arm's `skills_off`: names of official skills, checked against
    the catalog so a typo fails before the benchmark starts."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise BenchConfigError(f"{where}: 'skills_off' must be a list of skill names.")
    known = {s.name for s in official_skills()}
    unknown = [n for n in raw if n not in known]
    if unknown:
        raise BenchConfigError(
            f"{where}: 'skills_off' names no official skill: {', '.join(unknown)}. "
            f"Official skills: {', '.join(sorted(known))}."
        )
    return sorted(set(raw))


def load_bench_config(path: str = DEFAULT_BENCH_FILE) -> BenchConfig:
    """Parse and validate a benchmark file. Relative paths in it (the models
    file, a custom task folder) are relative to the current folder, like
    every other Certo path setting."""
    bench_path = Path(path)
    raw = _load_yaml(bench_path)
    where = str(bench_path)

    files = {}
    for key, name in (("models_file", MODELS_FILE), ("models_list_file", LIST_FILE)):
        value = raw.get(key) or ""
        if not isinstance(value, str):
            raise BenchConfigError(f"{where}: '{key}' must be a path.")
        if value and not Path(value).is_file():
            raise BenchConfigError(f"{where}: '{key}' names {value!r}, which doesn't exist.")
        found = find(name, value)
        if found is None:
            raise BenchConfigError(
                f"{where}: the benchmark takes its models, by name, from {MODELS_FILE} and "
                f"{LIST_FILE}. {missing_message(name, repr(key) + ' in the benchmark file')}"
            )
        files[key] = found
    optional = {}
    for key in ("escalation_file", "task_profiles_file"):
        value = raw.get(key) or ""
        if not isinstance(value, str):
            raise BenchConfigError(f"{where}: '{key}' must be a path.")
        if value and not Path(value).is_file():
            raise BenchConfigError(f"{where}: '{key}' names {value!r}, which doesn't exist.")
        optional[key] = value
    escalation_file, task_profiles_file = (
        optional["escalation_file"],
        optional["task_profiles_file"],
    )
    catalog_warnings: list[str] = []
    try:
        loaded = load_checked_catalog(
            files["models_file"],
            files["models_list_file"],
            escalation_file=escalation_file,
            task_profiles_file=task_profiles_file,
            on_warning=catalog_warnings.append,
            # A file that names its own models.yaml doesn't pick up the
            # ladders and profiles in the current folder: they name other
            # models.
            look_up_optional=not raw.get("models_file"),
        )
        catalog = {e.name: e for e in loaded.models}
    except ModelCatalogError as exc:
        raise BenchConfigError(f"model files for {where}: {exc}") from exc

    tasks_dir = raw.get("tasks_dir") or str(BUILTIN_TASKS_DIR)
    if not isinstance(tasks_dir, str):
        raise BenchConfigError(f"{where}: 'tasks_dir' must be a path.")
    try:
        available = load_tasks(tasks_dir)
    except BenchTaskError as exc:
        raise BenchConfigError(f"{where}: {exc}") from exc
    if not available:
        raise BenchConfigError(f"{where}: no tasks found in {tasks_dir}.")

    tasks = _tasks(raw.get("tasks"), available, where)
    arms = _arms(raw.get("arms"), catalog, where)
    _check_milestone_tasks(arms, tasks, where)
    return BenchConfig(
        path=str(bench_path.resolve()),
        tasks_dir=str(Path(tasks_dir).resolve()),
        tasks=tasks,
        repeats=_repeats(raw.get("repeats"), where),
        arms=arms,
        models_file=str(Path(files["models_file"]).resolve()),
        models_list_file=str(Path(files["models_list_file"]).resolve()),
        escalation_file=str(Path(escalation_file).resolve()) if escalation_file else "",
        task_profiles_file=str(Path(task_profiles_file).resolve()) if task_profiles_file else "",
        catalog=catalog,
        catalog_warnings=catalog_warnings,
        model_catalog=loaded,
    )
