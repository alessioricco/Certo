"""Pure data model, parsing, and scoring for `CERTO_MODEL_SELECTION=auto`'s
model catalog (`models.yaml`) — no SDK imports, no side effects beyond
reading the one file, fully unit-testable without a `Conversation`.

`models.yaml` is git-ignored (see `.gitignore`) because real API keys live
directly in it — same treatment as `.env`. `models.yaml.example` is the
checked-in template. See MANUAL.md "Automatic model selection" for the
user-facing writeup and DECISIONS.md for the design history
(deterministic weighted scoring was chosen over an LLM-based router; one
static ranked list per task, not re-scored mid-task; no hard minimum catalog
size — see `rank_candidates`).

Rating/weight axes are deliberately open-ended, not hardcoded to a fixed set
(`reasoning`/`cost`/`precision`/`code` are just the template's example) —
scoring iterates whatever keys a task profile's `weights` declares, so a
user can add a new axis with zero code changes.

Each model entry also has `activated` (bool, default `true`) — a
deactivated entry stays in the file (still schema-validated, still counted
for duplicate-name checks) but is excluded from `rank_candidates()`'s
scoring/output entirely, letting a user maintain a large catalog and
toggle individual models on/off without deleting or re-adding entries.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from .config import DEFAULT_LLM_TIMEOUT_SECONDS


class ModelCatalogError(ValueError):
    """Raised when `models.yaml` is missing, malformed, or fails schema
    validation. Message is user-facing."""


@dataclass(frozen=True)
class ModelCatalogEntry:
    """One candidate model. `api_key`/`base_url`/`reasoning_effort` mirror
    the exact same fields `.env`'s CERTO_LLM_API_KEY/CERTO_LLM_BASE_URL/
    CERTO_LLM_REASONING_EFFORT carry for the single-model default — see
    `model_selection.py`'s `llm_for_entry()`, which builds an actual `LLM`
    from one of these via `config.override_llm()`, not a separate builder.
    """

    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    # How long one call to this model may take; 0 = no limit. Not inherited
    # from CERTO_LLM_TIMEOUT_SECONDS: an entry is a complete model spec.
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    # The model's context window, in tokens; 0 = what the provider reports
    # (context_window.py). Not inherited from CERTO_LLM_CONTEXT_TOKENS.
    context_tokens: int = 0
    description: str = ""
    ratings: dict[str, float] = field(default_factory=dict)
    activated: bool = True
    # Whether models.yaml lists this model. A model that is only in
    # models_list.yaml is never used (and is not `activated`).
    configured: bool = True
    # The `${NAME}` variables models.yaml names for this model that aren't
    # set; such a model is left out (not `activated`).
    missing_vars: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskProfile:
    """A named weight vector, selected by keyword match against the task
    text — same `KeywordTrigger`-style deterministic matching this project's
    skills already use, not an LLM classification call."""

    name: str
    triggers: tuple[str, ...] = ()
    weights: dict[str, float] = field(default_factory=dict)
    # A catalog model's name to run first for this profile, whatever the
    # weights say. Used only when that model is enabled in models.yaml;
    # the weights still order the fallbacks.
    model: str | None = None


@dataclass(frozen=True)
class LadderRung:
    """One step of an explicit escalation ladder: a catalog model by name,
    optionally with its own fix-attempt budget and reasoning effort."""

    model: str
    retries: int | None = None  # None: CERTO_MAX_VERIFY_RETRIES
    reasoning_effort: str | None = None  # None: the model entry's own


@dataclass(frozen=True)
class Ladder:
    name: str
    rungs: tuple[LadderRung, ...]
    escalate_on_acceptance_failed: bool = False


DEFAULT_COST_AXIS = "cost"
DEFAULT_MAX_RUNGS = 3


@dataclass(frozen=True)
class EscalationSettings:
    """The optional top-level `escalation:` section (see escalation.py)."""

    cost_axis: str = DEFAULT_COST_AXIS
    # Whether `cost_axis` was written in the file: only then is an axis no
    # model is rated on an error (catalog_check.py).
    cost_axis_set: bool = False
    max_rungs: int = DEFAULT_MAX_RUNGS
    ladders: dict[str, Ladder] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCatalog:
    models: list[ModelCatalogEntry]
    task_profiles: list[TaskProfile]
    escalation: EscalationSettings = field(default_factory=EscalationSettings)
    # Problems between the two files that a non-strict load collects for
    # catalog_check.py instead of raising (duplicate or unknown names).
    load_problems: tuple[str, ...] = ()
    # Things to tell the user that don't stop a run, such as a section of
    # models_list.yaml that now belongs in its own file.
    load_warnings: tuple[str, ...] = ()


_DEFAULT_PROFILE = TaskProfile(name="default", triggers=(), weights={})


def _require_str(data: dict, key: str, *, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelCatalogError(f"{context}: {key!r} must be a non-empty string.")
    return value


def _optional_str(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelCatalogError(f"{key!r} must be a string if given.")
    value = value.strip()
    return value or None


def _parse_ratings(data: dict, *, context: str) -> dict[str, float]:
    raw = data.get("ratings", {}) or {}
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"{context}: 'ratings' must be a mapping of axis -> number.")
    ratings: dict[str, float] = {}
    for axis, value in raw.items():
        try:
            ratings[str(axis)] = float(value)
        except (TypeError, ValueError):
            raise ModelCatalogError(
                f"{context}: rating {axis!r} must be a number, got {value!r}."
            ) from None
    return ratings


def _parse_timeout(data: dict, *, context: str) -> int:
    if data.get("timeout_seconds") is None:
        return DEFAULT_LLM_TIMEOUT_SECONDS
    value = data["timeout_seconds"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelCatalogError(
            f"{context}: 'timeout_seconds' must be zero or a positive whole number "
            f"of seconds, got {value!r}."
        )
    return value


def _parse_context_tokens(data: dict, *, context: str) -> int:
    value = data.get("context_tokens")
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelCatalogError(
            f"{context}: 'context_tokens' must be zero or a positive whole number of tokens, "
            f"got {value!r}."
        )
    return value


def _parse_activated(data: dict, *, context: str) -> bool:
    if "activated" not in data:
        return True
    value = data["activated"]
    if not isinstance(value, bool):
        raise ModelCatalogError(f"{context}: 'activated' must be true or false, got {value!r}.")
    return value


def _parse_model_entry(data: Any) -> ModelCatalogEntry:
    if not isinstance(data, dict):
        raise ModelCatalogError("Each entry under 'models' must be a mapping.")
    name = _require_str(data, "name", context="A model entry")
    context = f"Model {name!r}"
    model = _require_str(data, "model", context=context)
    return ModelCatalogEntry(
        name=name,
        model=model,
        api_key=_optional_str(data, "api_key"),
        base_url=_optional_str(data, "base_url"),
        reasoning_effort=_optional_str(data, "reasoning_effort"),
        timeout_seconds=_parse_timeout(data, context=context),
        context_tokens=_parse_context_tokens(data, context=context),
        description=(_optional_str(data, "description") or ""),
        ratings=_parse_ratings(data, context=context),
        activated=_parse_activated(data, context=context),
    )


def _parse_weights(data: dict, *, context: str) -> dict[str, float]:
    raw = data.get("weights", {}) or {}
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"{context}: 'weights' must be a mapping of axis -> number.")
    weights: dict[str, float] = {}
    for axis, value in raw.items():
        try:
            weights[str(axis)] = float(value)
        except (TypeError, ValueError):
            raise ModelCatalogError(
                f"{context}: weight {axis!r} must be a number, got {value!r}."
            ) from None
    return weights


def _parse_task_profile(name: str, data: Any) -> TaskProfile:
    if not isinstance(data, dict):
        raise ModelCatalogError(f"Task profile {name!r} must be a mapping.")
    triggers_raw = data.get("triggers", []) or []
    if not isinstance(triggers_raw, list) or not all(isinstance(t, str) for t in triggers_raw):
        raise ModelCatalogError(f"Task profile {name!r}: 'triggers' must be a list of strings.")
    model = data.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ModelCatalogError(
            f"Task profile {name!r}: 'model' must be the name of a model in models_list.yaml."
        )
    return TaskProfile(
        name=name,
        triggers=tuple(triggers_raw),
        weights=_parse_weights(data, context=f"Task profile {name!r}"),
        model=model.strip() if model else None,
    )


_ESCALATION_KEYS = {"cost_axis", "max_rungs", "ladders"}
_LADDER_KEYS = {"rungs", "escalate_on_acceptance_failed"}
_RUNG_KEYS = {"model", "retries", "reasoning_effort"}


def _parse_rung(data: Any, *, context: str) -> LadderRung:
    if not isinstance(data, dict):
        raise ModelCatalogError(f"{context}: each rung must be a mapping with a 'model' name.")
    unknown = sorted(set(data) - _RUNG_KEYS)
    if unknown:
        raise ModelCatalogError(
            f"{context}: unknown key(s) {', '.join(unknown)}. "
            f"A rung takes: {', '.join(sorted(_RUNG_KEYS))}."
        )
    model = _require_str(data, "model", context=context)
    retries = data.get("retries")
    if retries is not None and (isinstance(retries, bool) or not isinstance(retries, int)):
        raise ModelCatalogError(f"{context}: 'retries' must be a whole number, got {retries!r}.")
    return LadderRung(
        model=model.strip(),
        retries=retries,
        reasoning_effort=_optional_str(data, "reasoning_effort"),
    )


def _parse_ladder(name: str, data: Any) -> Ladder:
    """A ladder is a list of rungs, or a mapping with `rungs` and options."""
    context = f"Escalation ladder {name!r}"
    options: dict[str, Any] = {}
    if isinstance(data, dict):
        unknown = sorted(set(data) - _LADDER_KEYS)
        if unknown:
            raise ModelCatalogError(
                f"{context}: unknown key(s) {', '.join(unknown)}. "
                f"A ladder written as a mapping takes: {', '.join(sorted(_LADDER_KEYS))}."
            )
        options = data
        data = data.get("rungs")
    if not isinstance(data, list):
        raise ModelCatalogError(f"{context} must be a list of rungs.")
    on_acceptance = options.get("escalate_on_acceptance_failed", False)
    if not isinstance(on_acceptance, bool):
        raise ModelCatalogError(
            f"{context}: 'escalate_on_acceptance_failed' must be true or false."
        )
    rungs = tuple(
        _parse_rung(rung, context=f"{context}, rung {i}") for i, rung in enumerate(data, start=1)
    )
    return Ladder(name=name, rungs=rungs, escalate_on_acceptance_failed=on_acceptance)


def _parse_escalation(raw: Any, path: str) -> EscalationSettings:
    if raw is None:
        return EscalationSettings()
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"{path}: 'escalation' must be a mapping.")
    unknown = sorted(set(raw) - _ESCALATION_KEYS)
    if unknown:
        raise ModelCatalogError(
            f"{path}: unknown key(s) under 'escalation': {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(_ESCALATION_KEYS))}."
        )
    cost_axis = raw.get("cost_axis")
    if cost_axis is not None and (not isinstance(cost_axis, str) or not cost_axis.strip()):
        raise ModelCatalogError(f"{path}: 'escalation.cost_axis' must be a rating axis name.")
    max_rungs = raw.get("max_rungs", DEFAULT_MAX_RUNGS)
    if isinstance(max_rungs, bool) or not isinstance(max_rungs, int) or max_rungs < 2:
        raise ModelCatalogError(
            f"{path}: 'escalation.max_rungs' must be a whole number of at least 2, "
            f"got {max_rungs!r}."
        )
    ladders_raw = raw.get("ladders") or {}
    if not isinstance(ladders_raw, dict):
        raise ModelCatalogError(f"{path}: 'escalation.ladders' must be a mapping of name -> rungs.")
    return EscalationSettings(
        cost_axis=cost_axis.strip() if cost_axis else DEFAULT_COST_AXIS,
        cost_axis_set=cost_axis is not None,
        max_rungs=max_rungs,
        ladders={str(name): _parse_ladder(str(name), data) for name, data in ladders_raw.items()},
    )


LIST_FILE = "models_list.yaml"
MODELS_FILE = "models.yaml"
# Optional, one per mode that reads them (0.1.20): --auto-model's task
# profiles, and --escalate's ladders. Before 0.1.20 both were sections of
# models_list.yaml; read there with a warning until 0.1.25, refused since.
PROFILES_FILE = "task_profiles.yaml"
ESCALATION_FILE = "escalation.yaml"
# Personal settings: they live in models.yaml, never in the shared list.
_PERSONAL_ONLY = ("api_key", "base_url", "activated")
_PERSONAL_KEYS = {
    "name",
    "api_key",
    "base_url",
    "activated",
    "ratings",
    "reasoning_effort",
    "timeout_seconds",
    "context_tokens",
    "description",
}


def _read_mapping(path: str) -> dict:
    file_path = Path(path)
    if not file_path.is_file():
        raise ModelCatalogError(f"{path} doesn't exist.")
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ModelCatalogError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"{path} must contain a mapping at the top level.")
    return raw


def _parse_profiles(raw: Any, path: str) -> list[TaskProfile]:
    profiles_raw = raw or {}
    if not isinstance(profiles_raw, dict):
        raise ModelCatalogError(f"{path}: 'task_profiles' must be a mapping of name -> profile.")
    return [_parse_task_profile(name, data) for name, data in profiles_raw.items()]


def _read_section_file(path: str, key: str) -> Any:
    """task_profiles.yaml or escalation.yaml: one top-level key, the same
    section models_list.yaml used to hold, so moving it is cut and paste.
    A file with only comments is fine: it sets nothing."""
    file_path = Path(path)
    try:
        if yaml.safe_load(file_path.read_text(encoding="utf-8")) is None:
            return None
    except (OSError, yaml.YAMLError):
        pass  # _read_mapping reports it
    raw = _read_mapping(path)
    extra = sorted(set(raw) - {key})
    if extra:
        raise ModelCatalogError(
            f"{path} may only contain '{key}:', but it has {', '.join(extra)}. "
            f"Models go in {LIST_FILE}, keys and addresses in {MODELS_FILE}."
        )
    return raw.get(key)


# The sections models_list.yaml had before 0.1.20, and their own files.
_MOVED_SECTIONS = {"task_profiles": PROFILES_FILE, "escalation": ESCALATION_FILE}


def _parse_list(path: str) -> list[ModelCatalogEntry]:
    """models_list.yaml: the models (ids, descriptions, ratings). No
    personal settings, and no task profiles or escalation settings, which
    have their own files since 0.1.20."""
    raw = _read_mapping(path)
    for key, own_file in _MOVED_SECTIONS.items():
        if raw.get(key) is not None:
            raise ModelCatalogError(
                f"{path} has the '{key}:' section. Since 0.1.20 it belongs in its own file, "
                f"{own_file}, next to {LIST_FILE}, and since 0.1.26 it is no longer read "
                "here: move the section there as it is. See "
                "docs/reference/models-yaml.md#moving-from-one-file-0119-and-earlier."
            )
    models_raw = raw.get("models")
    if not isinstance(models_raw, list) or not models_raw:
        raise ModelCatalogError(f"{path} must define a non-empty 'models' list.")
    for data in models_raw:
        if isinstance(data, dict):
            personal = [key for key in _PERSONAL_ONLY if key in data]
            if personal:
                raise ModelCatalogError(
                    f"{path}: model {data.get('name')!r} has {', '.join(personal)}. Those are "
                    f"personal settings and belong in {MODELS_FILE}, next to the model's name."
                )
    return [_parse_model_entry(entry) for entry in models_raw]


def _old_format_error(path: str, what: str) -> ModelCatalogError:
    return ModelCatalogError(
        f"{path} {what}. Since version 0.1.10, {MODELS_FILE} holds only your personal "
        f"settings: for each model, its `name` from {LIST_FILE} plus api_key, base_url, "
        f"activated and optional overrides. Model ids and descriptions go in "
        f"{LIST_FILE}, task_profiles in {PROFILES_FILE}, escalation in {ESCALATION_FILE}. "
        f"See docs/reference/models-yaml.md."
    )


def _parse_personal(path: str) -> list[dict]:
    """models.yaml: one entry per model the user wants, by name, with keys,
    addresses and optional overrides."""
    raw = _read_mapping(path)
    extra = sorted(set(raw) - {"models"})
    if extra:
        raise _old_format_error(path, f"has {', '.join(extra)}")
    entries = raw.get("models")
    if not isinstance(entries, list) or not entries:
        raise ModelCatalogError(
            f"{path} must define a non-empty 'models' list: the models from {LIST_FILE} "
            "you want to use, by name."
        )
    parsed = []
    for data in entries:
        if not isinstance(data, dict):
            raise ModelCatalogError(f"{path}: each entry under 'models' must be a mapping.")
        name = _require_str(data, "name", context=f"An entry in {path}")
        if "model" in data:
            raise _old_format_error(path, f"gives a model id for {name!r}")
        unknown = sorted(set(data) - _PERSONAL_KEYS)
        if unknown:
            raise ModelCatalogError(
                f"{path}: {name!r} has unknown key(s) {', '.join(unknown)}. Allowed: "
                f"{', '.join(sorted(_PERSONAL_KEYS))}."
            )
        context = f"{path}: {name!r}"
        entry: dict[str, Any] = {
            "name": name.strip(),
            "api_key": _optional_str(data, "api_key"),
            "base_url": _optional_str(data, "base_url"),
            "activated": _parse_activated(data, context=context),
        }
        if "ratings" in data:
            entry["ratings"] = _parse_ratings(data, context=context)
        if _optional_str(data, "reasoning_effort") is not None:
            entry["reasoning_effort"] = _optional_str(data, "reasoning_effort")
        if data.get("timeout_seconds") is not None:
            entry["timeout_seconds"] = _parse_timeout(data, context=context)
        if data.get("context_tokens") is not None:
            entry["context_tokens"] = _parse_context_tokens(data, context=context)
        if _optional_str(data, "description") is not None:
            entry["description"] = _optional_str(data, "description")
        parsed.append(entry)
    return parsed


def _merge(listed: ModelCatalogEntry, personal: dict | None) -> ModelCatalogEntry:
    if personal is None:
        return replace(listed, activated=False, configured=False)
    return replace(
        listed,
        api_key=personal["api_key"],
        base_url=personal["base_url"],
        activated=personal["activated"],
        configured=True,
        missing_vars=personal.get("missing_vars", ()),
        ratings={**listed.ratings, **personal.get("ratings", {})},
        reasoning_effort=personal.get("reasoning_effort", listed.reasoning_effort),
        timeout_seconds=personal.get("timeout_seconds", listed.timeout_seconds),
        context_tokens=personal.get("context_tokens", listed.context_tokens),
        description=personal.get("description", listed.description),
    )


# `${NAME}` in models.yaml's api_key and base_url: the key stays in the
# settings file (DECISIONS.md), models.yaml only names it.
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_vars(value: str | None, environ: Mapping[str, str]) -> tuple[str | None, list[str]]:
    """`value` with every `${NAME}` replaced from `environ`, and the names
    that were unset or blank."""
    if value is None:
        return None, []
    missing: list[str] = []

    def lookup(match: re.Match[str]) -> str:
        found = (environ.get(match.group(1)) or "").strip()
        if not found:
            missing.append(match.group(1))
        return found

    return _VAR_RE.sub(lookup, value).strip() or None, missing


def load_model_catalog(
    list_path: str,
    models_path: str,
    *,
    profiles_path: str | None = None,
    escalation_path: str | None = None,
    strict: bool = True,
    environ: Mapping[str, str] | None = None,
) -> ModelCatalog:
    """Build the catalog from `models_list.yaml` (the models) and
    `models.yaml` (which of them to use, with keys, addresses and
    overrides), plus the optional `task_profiles.yaml` and
    `escalation.yaml`. Ratings in models.yaml replace the list's axis by
    axis. A model missing from models.yaml is never used.

    Raises `ModelCatalogError` for a missing or malformed file, personal
    settings in the list, a `task_profiles:` or `escalation:` section
    still in the list (the layout before 0.1.20), and the pre-0.1.10
    single-file models.yaml. With
    `strict=False`, duplicate names and names models.yaml gives that the
    list doesn't have are collected in `load_problems` for
    `catalog_check.py` to report with everything else; commands load
    through `catalog_check.load_checked_catalog`. No minimum catalog size
    is enforced (see `rank_candidates()`).

    `${NAME}` in an `api_key` or `base_url` is read from `environ`
    (os.environ, which a run has filled from the settings files). A model
    whose variable is unset is left out, with a warning, rather than sent
    the literal text."""
    environ = os.environ if environ is None else environ
    listed = _parse_list(list_path)
    warnings: list[str] = []
    profiles = _parse_profiles(
        _read_section_file(profiles_path, "task_profiles") if profiles_path else None,
        profiles_path or list_path,
    )
    escalation = _parse_escalation(
        _read_section_file(escalation_path, "escalation") if escalation_path else None,
        escalation_path or list_path,
    )
    personal = _parse_personal(models_path)
    for data in personal:
        for key in ("api_key", "base_url"):
            data[key], missing = _expand_vars(data[key], environ)
            if missing and data["activated"]:
                data["activated"] = False
                data["missing_vars"] = (*data.get("missing_vars", ()), *missing)
                names = ", ".join(f"${{{name}}}" for name in missing)
                warnings.append(
                    f"{MODELS_FILE}: {data['name']!r} has {key} {names}, which isn't set in "
                    "your settings file or the environment, so this model is left out. Add "
                    f"{missing[0]}=... to your settings file."
                )
    problems: list[str] = []

    seen: set[str] = set()
    for entry in listed:
        # catalog_check reports a duplicate in the list itself.
        if strict and entry.name in seen:
            raise ModelCatalogError(f"{list_path}: duplicate model name {entry.name!r}.")
        seen.add(entry.name)
    by_name: dict[str, dict] = {}
    for data in personal:
        if data["name"] in by_name:
            problems.append(f"{MODELS_FILE} lists {data['name']!r} twice.")
        elif data["name"] not in seen:
            problems.append(
                f"{MODELS_FILE} names {data['name']!r}, which isn't in {LIST_FILE}. Check the "
                f"spelling, or add the model to {LIST_FILE}."
            )
        by_name.setdefault(data["name"], data)
    if strict and problems:
        raise ModelCatalogError(problems[0])

    merged: list[ModelCatalogEntry] = []
    done: set[str] = set()
    for entry in listed:
        merged.append(_merge(entry, by_name.get(entry.name) if entry.name not in done else None))
        done.add(entry.name)
    return ModelCatalog(
        models=merged,
        task_profiles=profiles,
        escalation=escalation,
        load_problems=tuple(problems),
        load_warnings=tuple(warnings),
    )


def task_title(task_text: str) -> str:
    """The line a task is classified by: its first line with text, without
    Markdown heading marks. A task file's title, or the whole task when it
    is one line. Matching the whole text made almost every task file
    `debugging`: a spec that says "raise ValueError" or "fix all build
    failures" contains `error` or `fix` (seen 2026-10-19 on 12 of 14 bundled
    tasks)."""
    for line in task_text.splitlines():
        if line.strip():
            return line.strip().lstrip("#").strip()
    return ""


def _trigger_pattern(trigger: str) -> re.Pattern[str]:
    # Whole words, any case, and a simple plural: `bug` matches "bugs",
    # `crash` "crashes", but `fix` never matches "prefix".
    return re.compile(r"(?<!\w)" + re.escape(trigger.lower()) + r"(?:s|es)?(?!\w)")


# The heading `milestones.milestone_task` gives the milestone a run is
# for. Its own title is classified before the task's, so a milestone
# called "Fix the flaky tests" is `debugging` in a task that isn't.
_MILESTONE_HEADING = re.compile(r"^## Now: milestone (\d+) of (\d+): (.+)$", re.MULTILINE)


def current_milestone(task_text: str) -> tuple[int, int, str] | None:
    """For one milestone's run of a task written in milestones: its number,
    the number of milestones and its title (from the `## Now:` heading
    `milestones.milestone_task` writes); otherwise `None`."""
    found = _MILESTONE_HEADING.search(task_text)
    if not found:
        return None
    return int(found.group(1)), int(found.group(2)), found.group(3).strip()


def classification_titles(task_text: str) -> list[str]:
    """The lines a task is classified by, in order: for one milestone of a
    task written in milestones, the milestone's title, then the task's
    title (`task_title`); otherwise the task's title alone."""
    titles = []
    milestone = current_milestone(task_text)
    if milestone:
        titles.append(milestone[2])
    titles.append(task_title(task_text))
    return [t for t in titles if t]


def find_trigger_in(task_text: str, profile: TaskProfile) -> tuple[str, str] | None:
    """The first of the profile's triggers found, and the title it was found
    in: the milestone's title first, then the task's."""
    for title in classification_titles(task_text):
        lowered = title.lower()
        for trigger in profile.triggers:
            if _trigger_pattern(trigger).search(lowered):
                return trigger, title
    return None


def find_trigger(task_text: str, profile: TaskProfile) -> str | None:
    """The first of the profile's triggers found in the task's titles."""
    found = find_trigger_in(task_text, profile)
    return found[0] if found else None


def classify_task(task_text: str, catalog: ModelCatalog) -> TaskProfile:
    """The titles of `classification_titles` are tried in order (a
    milestone's own title, then the task's); in each, the first declared
    task profile with a trigger in it (whole words) wins — same tie-break
    convention as `_LANGUAGE_MARKERS` in `verification.py`. Falls back to a
    profile named `default` if one is declared, else a synthesized
    empty-weights profile (every model scores 0 and the declared order
    breaks the tie — see `rank_candidates`).
    """
    for title in classification_titles(task_text):
        for profile in catalog.task_profiles:
            if profile.name == "default":
                continue
            if any(_trigger_pattern(t).search(title.lower()) for t in profile.triggers):
                return profile
    for profile in catalog.task_profiles:
        if profile.name == "default":
            return profile
    return _DEFAULT_PROFILE


def score_entry(entry: ModelCatalogEntry, weights: dict[str, float]) -> float:
    """Weighted sum over whatever axes `weights` declares — an axis a model
    doesn't rate itself on contributes 0, not an error."""
    return sum(entry.ratings.get(axis, 0.0) * weight for axis, weight in weights.items())


def capability(entry: ModelCatalogEntry, cost_axis: str) -> float:
    """How capable a model is, for escalation: the plain sum of its ratings
    on every axis except the cost axis. With the usual axes that is
    reasoning + precision + code. Task profiles don't change it: a ladder
    climbs by general capability, the same for every task."""
    return sum(value for axis, value in entry.ratings.items() if axis != cost_axis)


def rank_candidates(catalog: ModelCatalog, weights: dict[str, float]) -> list[ModelCatalogEntry]:
    """Every *activated* catalog model, scored against `weights` and sorted
    descending (stable — ties keep the file's declared order, via Python's
    stable sort over the already-declaration-ordered `catalog.models`).

    A model with `activated: false` is skipped entirely — not scored, not
    returned, never a fallback candidate — so a user can keep a large
    catalog on file and toggle individual models on/off without deleting or
    re-adding entries.

    No minimum length is enforced beyond "at least one activated model": a
    1- or 2-model catalog just produces a correspondingly short fallback
    chain, never an error for the model *count* — a user is free to add more
    models later without hitting a hidden validation cliff. Raises
    `ModelCatalogError` only if every model in the catalog is deactivated,
    since that leaves nothing to select from at all.
    """
    active = [entry for entry in catalog.models if entry.activated]
    if not active:
        raise ModelCatalogError(
            "Every model in the catalog has 'activated: false' — set at "
            "least one to 'true' before using CERTO_MODEL_SELECTION=auto."
        )
    return sorted(active, key=lambda entry: score_entry(entry, weights), reverse=True)


def rank_for_profile(
    catalog: ModelCatalog, profile: TaskProfile
) -> tuple[list[ModelCatalogEntry], str]:
    """The models to try for a task of this profile, in order, and one line
    saying how the first was chosen. A profile's `model`, when it is
    enabled, goes first and the rest follow by the weights; otherwise the
    weights decide, and the line says why the pinned model wasn't used."""
    ranked = rank_candidates(catalog, profile.weights)
    if profile.model is None:
        return ranked, "ranked by the profile's weights"
    pinned = next((m for m in ranked if m.name == profile.model), None)
    if pinned is not None:
        rest = [m for m in ranked if m is not pinned]
        return [pinned, *rest], f"the profile names {pinned.name}; fallbacks ranked by weights"
    known = any(m.name == profile.model for m in catalog.models)
    why = "isn't enabled in models.yaml" if known else "isn't in models_list.yaml"
    return ranked, f"the profile names {profile.model}, which {why}; ranked by weights"
