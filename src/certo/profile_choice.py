"""Choose the model for each kind of task, for `--auto-model`
(`certo init models`, and `certo init models --profiles` alone).

Each task profile in `task_profiles.yaml` can name a model (`model:`); it
then goes first for that kind of task, and the ratings order the others
behind it, as fallbacks. Here the user picks it from the models the
ratings rank highest, any other active model, or none (the ratings
decide). Only the `model:` lines are changed, as text, so the file's
comments stay. A user can also leave the local models out of
`--auto-model` (`activated: false` in models.yaml, kept as a backup
first).

`--auto-model` refuses to run without task profiles (api.load_run_ladder,
DECISIONS.md): without them every model ranks the same and the first one
in models_list.yaml would go first.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Mapping

import yaml

from .init_cmd import Prompter, _write_private
from .model_catalog import (
    ModelCatalog,
    ModelCatalogError,
    TaskProfile,
    load_model_catalog,
    rank_candidates,
    score_entry,
)
from .model_pricing import is_local

_SHOWN = 3  # the best-ranked models offered first, for each profile
_RATINGS = "Let the ratings decide"
_OTHER = "Another of your models"

NO_PROFILES = (
    "--auto-model needs task profiles (task_profiles.yaml): without them every "
    "model ranks the same, and the first one in models_list.yaml would go first. "
    'Run "certo init models --profiles" to choose a model for each kind of task '
    '(or "certo init models" to add models too).'
)


def set_profile_model(path: str, profile: str, model: str | None) -> None:
    """Write `model: NAME` in `profile`'s block of task_profiles.yaml, or
    remove it (`model` None). Only that line changes: the comments and the
    rest of the file stay as they are."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    header = re.compile(rf"^(\s+){re.escape(profile)}:\s*(#.*)?$")
    start = indent = None
    for i, line in enumerate(lines):
        match = header.match(line)
        if match:
            start, indent = i, len(match.group(1))
            break
    if start is None:
        raise ModelCatalogError(f"{path}: no task profile named {profile!r}.")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        text = lines[i]
        if text.strip() and not text.lstrip().startswith("#"):
            if len(text) - len(text.lstrip()) <= indent:
                end = i
                break
    inner = " " * (indent + 2)
    found = next((i for i in range(start + 1, end) if re.match(rf"^{inner}model:", lines[i])), None)
    if found is not None:
        if model is None:
            del lines[found]
        else:
            lines[found] = f"{inner}model: {model}"
    elif model is not None:
        lines.insert(start + 1, f"{inner}model: {model}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def leave_out_local(models_path: str, catalog: ModelCatalog) -> list[str]:
    """Turn off the local models in models.yaml (`activated: false`), after
    keeping it as models.yaml.bak. Returns their names. The file holds key
    references, never keys; nothing of it is printed."""
    local = {m.name for m in catalog.models if m.configured and m.activated and is_local(m)}
    if not local:
        return []
    with open(models_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for entry in data.get("models", []):
        if isinstance(entry, dict) and entry.get("name") in local:
            entry["activated"] = False
    shutil.copyfile(models_path, models_path + ".bak")
    header = "# Local models turned off for --auto-model by certo init models --profiles.\n"
    _write_private(models_path, header + yaml.safe_dump(data, sort_keys=False))
    return sorted(local)


def _when(profile: TaskProfile) -> str:
    if profile.name == "default":
        return "when no other kind matches"
    return f"title has: {', '.join(profile.triggers)}"


def _choose_one(prompter: Prompter, catalog: ModelCatalog, profile: TaskProfile) -> str | None:
    """The model the user wants first for `profile`, or None for the ratings."""
    ranked = rank_candidates(catalog, profile.weights)
    best = ranked[:_SHOWN]
    options = [f"{m.name}  (score {score_entry(m, profile.weights):g})" for m in best]
    options.append(_RATINGS)
    rest = ranked[_SHOWN:]
    if rest:
        options.append(_OTHER)
    names = [m.name for m in best]
    # The model the profile names already, else "the ratings decide".
    default = names.index(profile.model) if profile.model in names else len(best)
    index = prompter.choose(
        f"\n{profile.name} ({_when(profile)}): which model first?", options, default=default
    )
    if index < len(best):
        return best[index].name
    if options[index] == _RATINGS:
        return None
    other = prompter.choose("Which one?", [m.name for m in rest])
    return rest[other].name


def choose_profiles(
    prompter: Prompter,
    list_path: str,
    models_path: str,
    profiles_path: str,
    env: Mapping[str, str],
) -> None:
    """Ask, for each task profile, which model goes first, and write it."""
    catalog = load_model_catalog(
        list_path, models_path, profiles_path=profiles_path, strict=False, environ=env
    )
    if any(is_local(m) for m in catalog.models if m.configured and m.activated) and any(
        not is_local(m) for m in catalog.models if m.configured and m.activated
    ):
        index = prompter.choose(
            "\nShould --auto-model use your local models too?",
            [
                "Yes, local and cloud models",
                "No, only the cloud models (the local ones stay set up, turned off)",
            ],
        )
        if index == 1:
            names = leave_out_local(models_path, catalog)
            if names:
                prompter.say(
                    f"Turned off in {os.path.basename(models_path)} (old one kept as "
                    f"models.yaml.bak): {', '.join(names)}"
                )
            catalog = load_model_catalog(
                list_path, models_path, profiles_path=profiles_path, strict=False, environ=env
            )
    if not any(m.activated for m in catalog.models):
        prompter.say("No model is active, so there is nothing to choose.")
        return
    prompter.say(
        "\nFor each kind of task, choose the model that goes first. The others follow "
        "by their ratings, if it fails."
    )
    chosen: list[str] = []
    for profile in catalog.task_profiles:
        model = _choose_one(prompter, catalog, profile)
        set_profile_model(profiles_path, profile.name, model)
        chosen.append(f"  {profile.name}: {model or 'the ratings decide'}")
    prompter.say(f"\nSaved in {profiles_path}:")
    for line in chosen:
        prompter.say(line)
