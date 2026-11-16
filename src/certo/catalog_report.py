"""The model catalog part of `certo check`: what `models.yaml` holds, the
model order each task profile gives, the ladders, its problems, and (with
`--models`) a real tool-call test of every active model. With `--task`,
how `--auto-model` would route one task. Never prints a key."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from typing import TextIO

from . import __version__
from .catalog_check import check_catalog, usable_rungs
from .config import DEFAULT_MAX_ITERATIONS, Config, ConfigError
from .escalation import EscalationError, derive_ladder, describe_rung
from .model_catalog import (
    LIST_FILE,
    MODELS_FILE,
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogError,
    TaskProfile,
    classify_task,
    find_trigger_in,
    load_model_catalog,
    fit_note,
    rank_for_profile,
    task_title,
)
from .model_files import (
    find,
    is_built_in,
    layers_of,
    missing_message,
    resolve,
    resolve_optional,
)
from .milestones import MilestoneError, milestone_task, parse_milestones, written_in_milestones
from .model_pricing import is_local
from .model_selection import config_for_entry
from .run_stats import MIN_RUNS, measured_estimate

# llm_check.explain() names the CERTO_LLM_* settings; for a catalog entry the fix
# is in its models.yaml fields instead.
_FIELD_NAMES = {
    "CERTO_LLM_API_KEY in your settings": "its api_key in models.yaml",
    "CERTO_LLM_MODEL in your settings": "its model id in models_list.yaml",
    "CERTO_LLM_BASE_URL in your settings": "its base_url in models.yaml",
}


def _setting(name: str) -> str:
    return (os.environ.get(f"CERTO_{name}") or os.environ.get(f"HARNESS_{name}") or "").strip()


def entry_config(entry: ModelCatalogEntry) -> Config:
    """A Config with only this entry's model settings: nothing from .env."""
    base = Config(
        model=entry.model,
        api_key=None,
        base_url=None,
        workspace=".",
        max_iterations=DEFAULT_MAX_ITERATIONS,
        confirm_mode="never",
        execution="local",
    )
    return config_for_entry(base, entry)


# Models shown per profile in `certo check`; `certo check --task` shows all.
_PROFILE_MODELS_SHOWN = 3


def _ranked(catalog: ModelCatalog, profile: TaskProfile) -> list[tuple[str, str]]:
    """(name, note) per model, in the order --auto-model tries them. Empty
    when no model is active."""
    try:
        ranked, _how = rank_for_profile(catalog, profile)
    except ModelCatalogError:
        return []
    rows = []
    for entry in ranked:
        note = fit_note(entry, profile)
        if entry.name == profile.model:
            note = f"named by the profile, {note}"
        rows.append((entry.name, note))
    return rows


def _profile_lines(catalog: ModelCatalog) -> list[str]:
    """Each task profile, its trigger words and the models it would run,
    in the order they are checked: the first profile whose word is in the
    task's title wins, `default` when none is."""
    if not catalog.task_profiles:
        return []
    lines = ["  Task profiles (--auto-model), checked in this order:"]
    rows = [
        (p.name, f"title has: {', '.join(p.triggers) or '(no trigger words)'}", p)
        for p in catalog.task_profiles
        if p.name != "default"
    ]
    # The 'default' profile, or Certo's own (empty weights) when there is none.
    fallback = classify_task("", catalog)
    name = fallback.name if fallback in catalog.task_profiles else "(no 'default' profile)"
    rows.append((name, "when no other profile matches", fallback))
    for name, when, profile in rows:
        models = _ranked(catalog, profile)
        shown = ", ".join(f"{n} ({note})" for n, note in models[:_PROFILE_MODELS_SHOWN])
        if len(models) > _PROFILE_MODELS_SHOWN:
            shown += f", +{len(models) - _PROFILE_MODELS_SHOWN} more"
        lines.append(f"    {name}, {when}")
        lines.append(f"      {shown or 'no active model'}")
    return lines


def _catalog_lines(catalog: ModelCatalog) -> list[str]:
    active = [m.name for m in catalog.models if m.activated]
    inactive = [m.name for m in catalog.models if m.configured and not m.activated]
    unlisted = sum(not m.configured for m in catalog.models)
    lines = [f"  Active models: {', '.join(active) or 'none'}"]
    if inactive:
        lines.append(f"  Inactive models: {', '.join(inactive)}")
    if unlisted:
        lines.append(
            f"  {unlisted} other model(s) in models_list.yaml, not used (not in models.yaml)"
        )
    lines.extend(_profile_lines(catalog))
    for ladder in catalog.escalation.ladders.values():
        usable = usable_rungs(ladder, catalog)
        rungs = " -> ".join(r.model for r in usable) or "no usable rung"
        skipped = len(ladder.rungs) - len(usable)
        note = f" ({skipped} rung(s) skipped)" if skipped else ""
        lines.append(f"  Ladder '{ladder.name}': {rungs}{note}")
    try:
        derived = derive_ladder(catalog)
    except EscalationError:
        lines.append("  Derived ladder: none (no active model)")
    else:
        rungs = " -> ".join(describe_rung(r, scores=True) for r in derived.rungs)
        lines.append(f"  Derived ladder: {rungs}")
        if derived.skipped:
            lines.append(f"  Left out of the derived ladder: {', '.join(derived.skipped)}")
    return lines


def _few(names: list[str], shown: int = 6) -> list[str]:
    """At most `shown` names, then "and N more"."""
    if len(names) <= shown:
        return names
    return [*names[:shown], f"and {len(names) - shown} more"]


def _layer_changes(path: str) -> list[str]:
    """For a file read in layers, one line per layer above the lowest:
    which entries it changes and which it adds."""
    layers = layers_of(path)
    if len(layers) < 2:
        return []
    import yaml

    lines = []
    below: set[str] = set()
    for i, layer in enumerate(layers):
        try:
            raw = yaml.safe_load(open(layer, encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
        names = set()
        for key in ("models",):
            names |= {e.get("name") for e in raw.get(key) or [] if isinstance(e, dict)}
        for key in ("task_profiles",):
            names |= set(raw.get(key) or {})
        ladders = (raw.get("escalation") or {}).get("ladders") or {}
        names |= {f"ladder {n}" for n in ladders}
        names.discard(None)
        if i > 0:
            changed = _few(sorted(n for n in names if n in below))
            added = _few(sorted(n for n in names if n not in below))
            what = []
            if raw.get("replace") is True:
                what.append("replaces the layers below")
            if changed:
                what.append("changes " + ", ".join(changed))
            if added:
                what.append("adds " + ", ".join(added))
            lines.append(f"    + {layer}: {'; '.join(what) or 'no entries'}")
        below |= names
    return lines


def _print_path(out: TextIO, label: str, path: str | None, missing: str) -> None:
    if path is None:
        print(f"  {label}: {missing}", file=out)
        return
    layers = layers_of(path)
    first = f"built into Certo {__version__}" if is_built_in(layers[0]) else layers[0]
    print(f"  {label}: {first}", file=out)
    for line in _layer_changes(path):
        print(line, file=out)


def _print_ratings_source(out: TextIO, list_path: str) -> None:
    """Where the ratings come from: `certo models refresh`'s file (with a
    note when its data is old), Certo's hand ratings, or a list a setting
    names, read as written."""
    from .computed_ratings import age_notes, read_ratings_file, shipped_data, today

    if not is_built_in(layers_of(list_path)[0]):
        print("  Ratings: as written in the list", file=out)
        return
    found = read_ratings_file()
    if found is None:
        print(
            "  Ratings: Certo's, set by hand (certo models refresh computes them from "
            "current benchmark data)",
            file=out,
        )
        return
    print(
        f"  Ratings: computed by certo models refresh on {found.refreshed}, from model "
        f"data of {found.data} ({found.path})",
        file=out,
    )
    try:
        shipped = shipped_data().generated
    except (OSError, ValueError, KeyError):
        shipped = ""
    for note in age_notes(found, shipped, today()):
        print(f"  Note: {note}", file=out)


def _origin_lines(catalog: ModelCatalog) -> list[str]:
    """Per active model, where its ratings come from."""
    from .computed_ratings import origin, read_ratings_file

    found = read_ratings_file()
    if found is None:
        return []
    active = [m for m in catalog.models if m.activated]
    if not active:
        return []
    width = max(len(m.name) for m in active)
    lines = ["  Where the active models' ratings come from:"]
    for entry in active:
        lines.append(f"    {entry.name:{width}}  {origin(entry.name, entry.ratings, found)}")
    return lines


def _load_catalog(out: TextIO, project_dir: str = "") -> ModelCatalog | None:
    """Find and load the model files for `project_dir` (else the current
    folder), printing which ones are used and what each layer changes.
    None after printing the error."""
    models_file, list_file = _setting("MODELS_FILE"), _setting("MODELS_LIST_FILE")
    print("Model files:", file=out)
    try:
        list_path, models_path = resolve(models_file, list_file, project_dir)
        profiles_path, escalation_path = resolve_optional(
            _setting("TASK_PROFILES_FILE"), _setting("ESCALATION_FILE"), project_dir
        )
        # A project's own choice (certo models choose).
        from .project_models import project_file, read_strategy

        project = project_file(project_dir or _setting("WORKSPACE") or os.getcwd())
        if project is not None:
            profiles_path = _setting("TASK_PROFILES_FILE") or project
            escalation_path = _setting("ESCALATION_FILE") or project
            strategy = read_strategy(project) or "not set"
            print(f"  Project choice: {project} (strategy: {strategy})", file=out)
        _print_path(out, "List", list_path, "")
        _print_ratings_source(out, list_path)
        _print_path(out, "Personal settings", models_path, "")
        _print_path(out, "Task profiles", profiles_path, "none (optional, for --auto-model)")
        _print_path(out, "Escalation", escalation_path, "none (optional, for --escalate)")
        return load_model_catalog(
            list_path,
            models_path,
            profiles_path=profiles_path,
            escalation_path=escalation_path,
            strict=False,
        )
    except (ModelCatalogError, ConfigError) as exc:
        print(f"  Error: {exc}", file=out)
        print(file=out)
        return None


def print_task_routing(out: TextIO, task_text: str, project_dir: str = "") -> bool:
    """`certo check --task`: the profile --auto-model would pick for this
    task, why, and every model in the order it would try them. No model is
    called. False when the model files can't be loaded."""
    catalog = _load_catalog(out, project_dir)
    if catalog is None:
        return False
    print(file=out)
    title = task_title(task_text)
    print(f"Task title: {title or '(empty)'}", file=out)
    profile = classify_task(task_text, catalog)
    found = find_trigger_in(task_text, profile) if profile.name != "default" else None
    if found is not None:
        why = f'"{found[0]}" is in the title'
    elif profile in catalog.task_profiles:
        why = "no other profile's trigger word is in the title"
    else:
        why = "no profile matches and there is no 'default' profile; file order"
    print(
        f"Profile: {profile.name if profile in catalog.task_profiles else '(none)'} ({why})",
        file=out,
    )
    try:
        ranked_entries, how = rank_for_profile(catalog, profile)
    except ModelCatalogError as exc:
        print(f"  Error: {exc}", file=out)
        return False
    print(f"Models, in the order --auto-model tries them ({how}):", file=out)
    for i, (name, note) in enumerate(_ranked(catalog, profile), start=1):
        print(f"  {i}. {name} ({note})", file=out)
    print(
        "The first model runs the task. The next one takes over if its provider "
        "fails, or makes the fix attempt when the current model's work fails Certo's checks.",
        file=out,
    )
    if ranked_entries:
        kind = "milestone" if written_in_milestones(task_text) else "task"
        print(_measured_line(ranked_entries[0], kind, profile.name), file=out)
    _print_milestone_routing(out, task_text, catalog)
    return True


def _measured_line(entry: ModelCatalogEntry, kind: str, profile: str) -> str:
    """What `entry`'s recorded runs of this kind say to expect (run_stats.py)."""
    measured = measured_estimate(entry.model, kind, profile)
    if measured is None:
        return (
            f"Measured: fewer than {MIN_RUNS} {kind} runs of {entry.name} recorded, "
            "so cost estimates are a fixed guess."
        )
    if is_local(entry):
        measured = replace(measured, cost=0.0, cost_low=0.0, cost_high=0.0)
    return f"Measured for {entry.name}: {measured.describe()}."


def _print_milestone_routing(out: TextIO, task_text: str, catalog: ModelCatalog) -> None:
    """For a task file written in milestones: the profile and first model of
    each milestone, which is classified by its own title first."""
    if not written_in_milestones(task_text):
        return
    try:
        plan = parse_milestones(task_text)
    except MilestoneError:
        return
    print(
        "\nIt runs milestone by milestone. Each milestone is classified by its own "
        "title first, then by the task's:",
        file=out,
    )
    for milestone in plan.milestones:
        text = milestone_task(plan, milestone.number)
        profile = classify_task(text, catalog)
        found = find_trigger_in(text, profile) if profile.name != "default" else None
        if found is None:
            why = "no trigger word"
        elif found[1] == milestone.label:
            why = f'"{found[0]}" in the milestone\'s title'
        else:
            why = f'"{found[0]}" in the task\'s title'
        ranked = _ranked(catalog, profile)
        first = ranked[0][0] if ranked else "no active model"
        name = profile.name if profile in catalog.task_profiles else "(none)"
        print(f"  {milestone.number}. {milestone.label}: {name} ({why}), {first} first", file=out)


def print_catalog_report(
    out: TextIO,
    *,
    test_models: bool,
    timeout: int,
    check: Callable,
    explain: Callable,
    project_dir: str = "",
) -> bool:
    """Print the catalog report; return False on any error or failed test.

    `check`/`explain` are llm_check's `check_tool_calling`/`explain`, passed
    in so tests can fake the model call."""
    models_file, list_file = _setting("MODELS_FILE"), _setting("MODELS_LIST_FILE")
    found = (
        find(LIST_FILE, list_file, project_dir),
        find(MODELS_FILE, models_file, project_dir),
    )
    if found == (None, None):
        if test_models:
            print(f"--models: {missing_message(MODELS_FILE, 'CERTO_MODELS_FILE')}", file=out)
            return False
        print(
            "Model files: none, so Certo uses the one model above. To use more than one "
            "(--auto-model, --escalate), run: certo init models",
            file=out,
        )
        print(file=out)
        return True
    catalog = _load_catalog(out, project_dir)
    if catalog is None:
        return False
    report = check_catalog(catalog)
    for line in _catalog_lines(catalog):
        print(line, file=out)
    for line in _origin_lines(catalog):
        print(line, file=out)
    for error in report.errors:
        print(f"  Error: {error}", file=out)
    for warning in report.warnings:
        print(f"  Warning: {warning}", file=out)
    ok = report.ok
    if test_models:
        active = [m for m in catalog.models if m.activated]
        print("Checking every active model:", file=out)
        for entry in active:
            print(f"  {entry.name} ({entry.model})...", end=" ", file=out, flush=True)
            result = check(entry_config(entry), timeout=timeout)
            text = explain(result, None)
            for old, new in _FIELD_NAMES.items():
                text = text.replace(old, new)
            print(text, file=out)
            ok = ok and result.ok
    print(file=out)
    return ok
