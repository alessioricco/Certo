"""Benchmark strategies: how one arm turns a task into a finished workspace.

A strategy is one entry in `STRATEGIES`. It knows which keys it reads from a
`bench.yaml` arm (`parse`), which `models.yaml` entries it uses (`models`),
and how to run one task in a prepared workspace (`run`). The bench runner
only uses this interface, so a later strategy, such as `best_of` (N
attempts, the verifier picks), is one new class and one new entry here,
with no change to the runner. `single` is one model; `escalate` climbs a
ladder of models (escalation.py), explicit or derived from the ratings
(the same ladder for every task); `auto` picks a model per task from the
task profiles, with fallbacks, as `certo --auto-model` does.

Models always come from the `models.yaml` catalog, by name, and reach the
normal Certo pipeline as an explicit configuration: never through `.env`.
No SDK import: the pipeline (`runner.stream_task`) is passed in by the
caller, so this module is testable with a fake.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .config import DEFAULT_MAX_ITERATIONS, ESCALATION_HANDOFFS, Config, override_llm
from .escalation import derive_ladder, ladder_from_models
from .model_catalog import ModelCatalog, ModelCatalogEntry


class BenchConfigError(ValueError):
    """A bench.yaml problem. The message is user-facing."""


@dataclass(frozen=True)
class RunContext:
    """Everything a strategy needs to run one task once."""

    task_text: str
    workspace: str
    catalog: Mapping[str, ModelCatalogEntry]
    # An empty folder of its own: user skills, third-party skills and
    # projects are pointed here, so only Certo's built-in skills load and no
    # file outside the run can change it.
    isolation_dir: str
    # runner.stream_task, or a fake in tests.
    stream: Callable[..., Any]
    # The whole catalog, with task profiles and escalation settings, for
    # strategies that build a ladder.
    model_catalog: ModelCatalog | None = None


@dataclass(frozen=True)
class AttemptResult:
    """What a strategy reports back: the fields of Certo's TaskOutcome the
    benchmark records, plus the catalog names it actually used."""

    verification_state: str
    retries_used: int
    run_summary: Any  # run_summary.RunSummary | None
    models_used: tuple[str, ...]
    # Escalation only: one dict per rung that ran, and the rung whose
    # verdict this is.
    rungs: tuple[dict[str, Any], ...] = ()
    final_rung: int | None = None
    # independent_tests.IndependentTestsResult, when the arm turns them on.
    independent_tests: Any = None
    # Auto only: the task profile the task was classified as.
    task_profile: str | None = None
    # How many tool-call reminders the run's conversation(s) were sent
    # (TaskOutcome.tool_call_reminders; summed over rungs for an escalation).
    tool_call_reminders: int = 0


class Strategy(Protocol):
    name: str
    description: str

    def parse(
        self, arm: Mapping[str, Any], catalog: Mapping[str, ModelCatalogEntry], where: str
    ) -> dict[str, Any]: ...

    def models(self, params: Mapping[str, Any]) -> list[str]: ...

    def run(self, ctx: RunContext, params: Mapping[str, Any]) -> AttemptResult: ...


def run_config(entry: ModelCatalogEntry, workspace: str, isolation_dir: str) -> Config:
    """The Config for one run: Certo's defaults, the catalog entry's model
    settings, and nothing read from `.env` or the user settings file. An
    entry's empty field stays empty (a local model never inherits another
    provider's key), as with `--auto-model`'s catalog entries."""
    base = Config(
        model=entry.model,
        api_key=None,
        base_url=None,
        workspace=workspace,
        max_iterations=DEFAULT_MAX_ITERATIONS,
        confirm_mode="never",
        execution="local",
        projects_dir=os.path.join(isolation_dir, "projects"),
        global_skills_dir=os.path.join(isolation_dir, "global_skills"),
        no_worktree_warning=True,
    )
    return override_llm(
        base,
        model=entry.model,
        api_key=entry.api_key or "",
        base_url=entry.base_url or "",
        reasoning_effort=entry.reasoning_effort or "",
        timeout_seconds=entry.timeout_seconds,
        context_tokens=entry.context_tokens,
    )


def arm_config(entry: ModelCatalogEntry, ctx: RunContext, params: Mapping[str, Any]) -> Config:
    """run_config, plus the arm's own options (`independent_tests`,
    `condense`, `context_tokens`, `max_task_seconds`,
    `tool_call_reminders`, `skills_off`; bench_config._ARM_OPTIONS)."""
    cfg = run_config(entry, ctx.workspace, ctx.isolation_dir)
    if params.get("independent_tests"):
        cfg = replace(cfg, independent_tests=True)
    if params.get("condense") is False:
        cfg = replace(cfg, condense=False)
    if params.get("context_tokens"):
        cfg = replace(cfg, llm_context_tokens=params["context_tokens"])
    if params.get("max_task_seconds"):
        cfg = replace(cfg, max_task_seconds=params["max_task_seconds"])
    if "tool_call_reminders" in params:
        cfg = replace(cfg, tool_call_reminders=params["tool_call_reminders"])
    if params.get("skills_off"):
        cfg = replace(cfg, skills_off=tuple(params["skills_off"]))
    return cfg


def model_name(
    arm: Mapping[str, Any], key: str, catalog: Mapping[str, ModelCatalogEntry], where: str
) -> str:
    """Read one catalog name from an arm, with an error that lists the
    names the catalog has."""
    value = arm.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchConfigError(f"{where}: '{key}' must be a model name from models.yaml.")
    if value not in catalog:
        names = ", ".join(sorted(catalog)) or "(none)"
        raise BenchConfigError(f"{where}: unknown model {value!r}. The models file has: {names}.")
    if not catalog[value].configured:
        raise BenchConfigError(
            f"{where}: model {value!r} is in models_list.yaml but not in models.yaml. List it "
            "in models.yaml, with its key or address, to benchmark it."
        )
    if catalog[value].missing_vars:
        names = ", ".join(f"${{{name}}}" for name in catalog[value].missing_vars)
        raise BenchConfigError(
            f"{where}: model {value!r} uses {names} in models.yaml, which isn't set in your "
            "settings file or the environment. Set it to benchmark this model."
        )
    if not catalog[value].activated:
        raise BenchConfigError(
            f"{where}: model {value!r} has 'activated: false' in models.yaml, and Certo never "
            "uses an inactive model. Set 'activated: true' on it to benchmark it."
        )
    return value


def reject_unknown_keys(arm: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(arm) - allowed - {"name", "strategy"})
    if extra:
        raise BenchConfigError(
            f"{where}: unknown key(s) {', '.join(extra)}. This strategy takes: "
            f"name, strategy, {', '.join(sorted(allowed))}, independent_tests, condense, "
            "context_tokens, max_task_seconds."
        )


class SingleStrategy:
    """One model, the normal Certo run: exactly what `certo "<task>"` does."""

    name = "single"
    description = "one model, the normal Certo run"

    def parse(self, arm, catalog, where):
        reject_unknown_keys(arm, {"model"}, where)
        return {"model": model_name(arm, "model", catalog, where)}

    def models(self, params):
        return [params["model"]]

    def run(self, ctx, params):
        entry = ctx.catalog[params["model"]]
        cfg = arm_config(entry, ctx, params)
        outcome = ctx.stream(ctx.task_text, cfg=cfg)
        return AttemptResult(
            verification_state=outcome.verification_state,
            retries_used=outcome.retries_used,
            run_summary=outcome.run_summary,
            models_used=(entry.name,),
            independent_tests=getattr(outcome, "independent_tests", None),
            tool_call_reminders=getattr(outcome, "tool_call_reminders", 0),
        )


class EscalateStrategy:
    """Start on the first model, climb to the next only when Certo's
    verdict shows the model couldn't finish or its provider failed: what
    `certo --escalate` does. `models: [a, b, ...]` is an explicit ladder; without it, the
    ladder derived from the active models' ratings."""

    name = "escalate"
    description = "a ladder of models, climbing on verification failure"

    def parse(self, arm, catalog, where):
        reject_unknown_keys(arm, {"models", "handoff"}, where)
        # Kept out of params at its default, so older results folders still
        # match on --resume.
        handoff = arm.get("handoff", "continue")
        if handoff not in ESCALATION_HANDOFFS:
            raise BenchConfigError(
                f"{where}: 'handoff' must be one of: {', '.join(ESCALATION_HANDOFFS)}."
            )
        extra = {"handoff": handoff} if handoff != "continue" else {}
        if "models" not in arm:
            active = [name for name, entry in catalog.items() if entry.activated]
            return {"models": None, "derived_models": active, **extra}
        names = arm["models"]
        if not isinstance(names, list) or len(names) < 2:
            raise BenchConfigError(
                f"{where}: 'models' must list at least two models from models.yaml, in the "
                "order to climb (or leave it out for the ladder derived from the ratings)."
            )
        if len(set(names)) != len(names):
            raise BenchConfigError(f"{where}: 'models' lists a model twice.")
        for i, _ in enumerate(names):
            model_name({"models": names[i]}, "models", catalog, where)
        return {"models": list(names), **extra}

    def models(self, params):
        return params["models"] if params["models"] is not None else params["derived_models"]

    def run(self, ctx, params):
        catalog = ctx.model_catalog
        if params["models"] is None:
            ladder = derive_ladder(catalog)
        else:
            ladder = ladder_from_models(catalog, params["models"])
        cfg = arm_config(ladder.rungs[0].entry, ctx, params)
        cfg = replace(cfg, escalation_handoff=params.get("handoff", "continue"))
        outcome = ctx.stream(ctx.task_text, cfg=cfg, ladder=ladder)
        rungs = tuple(
            {**r.to_dict(), "final": r.number == outcome.final_rung} for r in outcome.rungs
        )
        return AttemptResult(
            verification_state=outcome.verification_state,
            retries_used=outcome.retries_used,
            run_summary=outcome.run_summary,
            models_used=tuple(r.name for r in outcome.rungs),
            rungs=rungs,
            final_rung=outcome.final_rung,
            independent_tests=getattr(outcome, "independent_tests", None),
            tool_call_reminders=getattr(outcome, "tool_call_reminders", 0),
        )


def auto_catalog(catalog: ModelCatalog, names: list[str]) -> ModelCatalog:
    """The catalog narrowed to an arm's candidate models, in the catalog's
    order (the ranking breaks ties by it). Task profiles stay."""
    return replace(catalog, models=[m for m in catalog.models if m.name in names])


class AutoStrategy:
    """What `certo --auto-model` does: classify the task by its first line
    (task_profiles.yaml), start on the best-rated model for that profile,
    and fall back to the next on a provider failure or a failed fix
    attempt. `models: [a, b, ...]` limits the candidates; without it, every
    active model is one."""

    name = "auto"
    description = "a model picked per task from the task profiles, with fallbacks"

    def parse(self, arm, catalog, where):
        reject_unknown_keys(arm, {"models"}, where)
        if "models" not in arm:
            active = [name for name, entry in catalog.items() if entry.activated]
            if not active:
                raise BenchConfigError(f"{where}: models.yaml has no active model to choose from.")
            return {"models": None, "candidates": active}
        names = arm["models"]
        if not isinstance(names, list) or not names:
            raise BenchConfigError(
                f"{where}: 'models' must list the models from models.yaml to choose from (or "
                "leave it out to choose from every active model)."
            )
        if len(set(names)) != len(names):
            raise BenchConfigError(f"{where}: 'models' lists a model twice.")
        for name in names:
            model_name({"models": name}, "models", catalog, where)
        return {"models": list(names)}

    def models(self, params):
        return params["models"] if params["models"] is not None else params["candidates"]

    def run(self, ctx, params):
        catalog = auto_catalog(ctx.model_catalog, self.models(params))
        # The run's own settings; the models come from the catalog.
        cfg = replace(arm_config(catalog.models[0], ctx, params), model_selection="auto")
        outcome = ctx.stream(ctx.task_text, cfg=cfg, model_catalog=catalog)
        decisions = getattr(outcome, "model_decisions", ())
        used = tuple(dict.fromkeys(d.chosen_name for d in decisions if d.chosen_name))
        used = used or (catalog.models[0].name,)
        return AttemptResult(
            verification_state=outcome.verification_state,
            retries_used=outcome.retries_used,
            run_summary=outcome.run_summary,
            models_used=used,
            independent_tests=getattr(outcome, "independent_tests", None),
            task_profile=decisions[0].task_profile if decisions else None,
            tool_call_reminders=getattr(outcome, "tool_call_reminders", 0),
        )


# The registry. A new strategy is one more entry.
STRATEGIES: dict[str, Strategy] = {
    s.name: s for s in (SingleStrategy(), EscalateStrategy(), AutoStrategy())
}
