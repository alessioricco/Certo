"""Consistency checks for `models.yaml`, shared by every command that loads
it: `--auto-model`, `--escalate`, `certo bench` and `certo check`.

`check_catalog` returns every problem at once, in plain words naming the
model, ladder or profile. Errors stop the command; warnings are printed and
the command runs. A problem only one mode cares about (a ladder for
`--escalate`, a profile's `model:` for `--auto-model`) is a warning in the
other mode, so a broken ladder never stops an `--auto-model` run. `load_checked_catalog` is the one way commands load the
file. Pure: no SDK, no network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from .model_catalog import (
    Ladder,
    LadderRung,
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogError,
    capability,
    load_model_catalog,
)
from .model_files import resolve, resolve_optional


@dataclass
class CatalogReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def usable_rungs(ladder: Ladder, catalog: ModelCatalog) -> list[LadderRung]:
    """The rungs of `ladder` whose model exists and is active, in order."""
    by_name = {m.name: m for m in catalog.models}
    return [r for r in ladder.rungs if r.model in by_name and by_name[r.model].activated]


def _names(models: list[ModelCatalogEntry]) -> str:
    return ", ".join(m.name for m in models) or "(none)"


# What each mode doesn't use, and the note its problems get there.
_UNUSED_BY_MODE = {
    "auto": ("escalation", "Only --escalate uses ladders, so this run goes on."),
    "escalate": ("profiles", "Only --auto-model uses task profiles, so this run goes on."),
}


def check_catalog(catalog: ModelCatalog, *, mode: str | None = None) -> CatalogReport:
    """Every problem in the model files. `mode` is the run's model
    selection ("auto" or "escalate"): problems in the part of the files the
    mode doesn't use become warnings. None (certo check, certo bench) keeps
    them all errors."""
    report = CatalogReport()
    errors, warnings = report.errors, report.warnings
    # Errors in the escalation settings and in task profiles, kept apart
    # until `mode` decides whether they stop the command.
    ladder_errors: list[str] = []
    profile_errors: list[str] = []
    by_name: dict[str, ModelCatalogEntry] = {}
    errors.extend(catalog.load_problems)
    warnings.extend(catalog.load_warnings)
    for entry in catalog.models:
        if entry.name in by_name:
            errors.append(
                f"Two models in models_list.yaml are named {entry.name!r}. Model names must be "
                "unique."
            )
        by_name.setdefault(entry.name, entry)
    active = [m for m in catalog.models if m.activated]
    if not active:
        errors.append(
            "No model is enabled, so there is nothing Certo can use. List the models you "
            "want in models.yaml, by name, without 'activated: false'."
        )

    settings = catalog.escalation
    if settings.cost_axis_set and not any(settings.cost_axis in m.ratings for m in catalog.models):
        ladder_errors.append(
            f"escalation.cost_axis is {settings.cost_axis!r}, but no model has a rating "
            "with that name. Use the axis your ratings use for cost-effectiveness (usually "
            "'cost')."
        )

    for ladder in settings.ladders.values():
        where = f"Ladder {ladder.name!r}"
        seen: set[tuple[str, str | None]] = set()
        for i, rung in enumerate(ladder.rungs, start=1):
            if rung.model not in by_name:
                ladder_errors.append(
                    f"{where}, rung {i}: there is no model named {rung.model!r}. "
                    f"Models: {_names(catalog.models)}."
                )
            elif not by_name[rung.model].configured:
                warnings.append(
                    f"{where}, rung {i}: {rung.model} isn't in models.yaml, so this rung is "
                    "skipped."
                )
            elif not by_name[rung.model].activated:
                warnings.append(
                    f"{where}, rung {i}: {rung.model} has 'activated: false', so this rung "
                    "is skipped."
                )
            key = (rung.model, rung.reasoning_effort)
            if key in seen:
                ladder_errors.append(f"{where} lists {rung.model} twice with the same settings.")
            seen.add(key)
            if rung.retries is not None and rung.retries < 0:
                ladder_errors.append(
                    f"{where}, rung {i} ({rung.model}): retries must be 0 or more, "
                    f"got {rung.retries}."
                )
        usable = usable_rungs(ladder, catalog)
        if not usable:
            ladder_errors.append(
                f"{where} has no usable rung: none of its models is enabled in models.yaml."
            )
        elif len(usable) == 1:
            warnings.append(
                f"{where} has only one usable rung ({usable[0].model}), so it can't escalate."
            )
        scores = [(r.model, capability(by_name[r.model], settings.cost_axis)) for r in usable]
        for (low_name, low), (high_name, high) in pairwise(scores):
            if high < low:
                warnings.append(
                    f"{where}: {high_name} (capability {high:g}) comes after {low_name} "
                    f"(capability {low:g}) but is rated less capable. Allowed, but check "
                    "the order."
                )

    for profile in catalog.task_profiles:
        if profile.model is None:
            continue
        where = f"Task profile {profile.name!r}"
        if profile.model not in by_name:
            profile_errors.append(
                f"{where}: there is no model named {profile.model!r}. "
                f"Models: {_names(catalog.models)}."
            )
        elif not by_name[profile.model].activated:
            warnings.append(
                f"{where}: {profile.model} isn't enabled in models.yaml, so tasks of this "
                "profile use the model the weights rank first."
            )

    unused, note = _UNUSED_BY_MODE.get(mode, (None, ""))
    for part, problems in (("escalation", ladder_errors), ("profiles", profile_errors)):
        if part == unused:
            warnings.extend(f"{problem} {note}" for problem in problems)
        else:
            errors.extend(problems)

    weighted: dict[str, list[str]] = {}
    for profile in catalog.task_profiles:
        for axis, weight in profile.weights.items():
            if weight:
                weighted.setdefault(axis, []).append(profile.name)
    for entry in active:
        missing = [axis for axis in weighted if axis not in entry.ratings]
        if missing:
            profiles = sorted({p for axis in missing for p in weighted[axis]})
            warnings.append(
                f"Model {entry.name!r} has no rating for {', '.join(missing)}, which "
                f"task profile(s) {', '.join(profiles)} weigh: it counts as 0."
            )
        if not entry.api_key and not entry.base_url:
            warnings.append(
                f"Model {entry.name!r} has no api_key and no base_url: it works only if the "
                "provider's own key variable (such as OPENAI_API_KEY) is set."
            )
    return report


def load_checked_catalog(
    models_file: str = "",
    models_list_file: str = "",
    *,
    task_profiles_file: str = "",
    escalation_file: str = "",
    on_warning: Callable[[str], None] | None = None,
    mode: str | None = None,
    look_up_optional: bool = True,
) -> ModelCatalog:
    """Find, load and check the model files (see model_files.py; "" means
    look them up; task_profiles.yaml and escalation.yaml are optional).
    With `look_up_optional=False`, "" for one of the optional two means
    none. Raises `ModelCatalogError` listing every error; passes each
    warning to `on_warning`. `mode` as in `check_catalog`."""
    list_path, models_path = resolve(models_file, models_list_file)
    if look_up_optional:
        profiles_path, escalation_path = resolve_optional(task_profiles_file, escalation_file)
    else:
        profiles_path, escalation_path = task_profiles_file or None, escalation_file or None
    catalog = load_model_catalog(
        list_path,
        models_path,
        profiles_path=profiles_path,
        escalation_path=escalation_path,
        strict=False,
    )
    report = check_catalog(catalog, mode=mode)
    if report.errors:
        raise ModelCatalogError(
            f"{list_path} and {models_path} have {len(report.errors)} problem(s):\n"
            + "\n".join(f"  - {e}" for e in report.errors)
        )
    if on_warning is not None:
        for warning in report.warnings:
            on_warning(warning)
    return catalog
