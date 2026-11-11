"""`certo init models`: set up more than one model, for `--auto-model` and
`--escalate`, without editing a file.

It starts from the model `certo init` already saved, offers the models of
the example list that this computer can reach (the Ollama models
installed on the server, the cloud models whose key is in the settings or
the environment), and lets the user add a key for another provider or
type any other LiteLLM model id. Every chosen model is tested with the
same small request as `certo check --models`; only the ones that pass are
written. Then it shows what `--auto-model` and `--escalate` would do with
them, and asks which mode to use for every run, one model being the
default. With `--auto-model` it then asks which model goes first for each
kind of task (profile_choice.py); `--profiles` asks only that, for the
models already set up.

Keys are written only to the user settings file; `models.yaml` names them
as `${VAR}` (DECISIONS.md). Ratings are never invented: a model that
isn't in the list is rated by the user, or not used.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import yaml

from . import menus as _menus
from .catalog_report import _profile_lines, entry_config
from .config import load_settings_files, user_settings_path
from .escalation import EscalationError, derive_ladder, describe_rung
from .init_cmd import (
    CHECK_TIMEOUT_SECONDS,
    Cancelled,
    Prompter,
    _quote,
    _write_private,
    fetch_ollama_models,
    load_providers,
    normalize_base_url,
)
from .llm_check import LLMCheckResult, check_tool_calling, explain
from .model_catalog import (
    LIST_FILE,
    MODELS_FILE,
    PROFILES_FILE,
    ModelCatalogEntry,
    ModelCatalogError,
    _parse_list,
    load_model_catalog,
)
from .model_files import example_path, find, resolve
from .models_cmd import save_base
from .profile_choice import choose_profiles

# The rating axes the example list uses, asked in this order for a model
# the list doesn't have.
_AXES = ("reasoning", "precision", "code", "cost")
_MODES = (
    ("manual", "Just one model, without --auto-model or --escalate"),
    ("auto", "--auto-model: a model for each kind of task"),
    ("escalate", "--escalate: start cheap, move to the next model when one can't finish"),
)
_ANOTHER = "Another model (type any LiteLLM model id)"


@dataclass
class Candidate:
    """A model the user can add. `personal` is its models.yaml entry (keys
    only as `${VAR}`); `listed` is False for a model the list doesn't have,
    which needs the user's ratings."""

    entry: ModelCatalogEntry
    personal: dict
    group: str
    note: str = ""
    selected: bool = False
    listed: bool = True


@dataclass
class _Action:
    label: str
    provider: object | None = None  # a Provider: ask for its key


@dataclass
class _Setup:
    """What the run collects, written only at the end."""

    candidates: list[Candidate] = field(default_factory=list)
    new_keys: dict[str, str] = field(default_factory=dict)  # never printed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo init models",
        description=(
            "Set up more than one model, for --auto-model and --escalate. Starts from "
            "the model certo init saved, offers the models this computer can reach, "
            "tests each one with a small real request, writes models.yaml (and the "
            "example models_list.yaml and task_profiles.yaml when missing) to the user "
            "settings folder, and asks which mode to use for every run. Keys go only "
            "to the user settings file. Needs a terminal."
        ),
    )
    parser.add_argument(
        "--profiles",
        action="store_true",
        help=(
            "Only choose the model that goes first for each kind of task "
            "(task_profiles.yaml), for --auto-model, from the models already set up."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=CHECK_TIMEOUT_SECONDS,
        help=f"Seconds to wait for each model's answer (default {CHECK_TIMEOUT_SECONDS}).",
    )
    return parser


def _ratings_text(entry: ModelCatalogEntry) -> str:
    return " · ".join(f"{axis} {entry.ratings[axis]:g}" for axis in _AXES if axis in entry.ratings)


def _prefix(model: str) -> str:
    prefix = model.split("/", 1)[0] if "/" in model else ""
    return "ollama" if prefix == "ollama_chat" else prefix


def _unique_name(base: str, taken: set[str]) -> str:
    """A model name for models the list doesn't have, unlike every name
    already taken (the list's, and the ones made up so far)."""
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def _host(url: str) -> str:
    return url.split("://", 1)[-1].rstrip("/")


def _gather(
    listed: list[ModelCatalogEntry],
    env: Mapping[str, str],
    fetch_models: Callable[[str], list[str]],
    prompter: Prompter,
) -> tuple[list[Candidate], list[_Action]]:
    """The candidates this computer can reach, and the actions offered
    after them (a key for each provider without one, another model)."""
    main_model = (env.get("CERTO_LLM_MODEL") or "").strip()
    main_url = (env.get("CERTO_LLM_BASE_URL") or "").strip()
    main_key = bool((env.get("CERTO_LLM_API_KEY") or "").strip())
    by_model = {e.model: e for e in listed}
    taken = {e.name for e in listed}
    candidates: list[Candidate] = []

    if main_model:
        personal: dict = {}
        if main_key:
            personal["api_key"] = "${CERTO_LLM_API_KEY}"
        if main_url:
            personal["base_url"] = main_url
        entry = by_model.get(main_model)
        if entry is None:
            base = main_model.split("/", 1)[-1].replace(":", "-").replace("/", "-")
            entry = ModelCatalogEntry(name=_unique_name(base, taken), model=main_model)
        candidates.append(
            Candidate(
                entry,
                {"name": entry.name, **personal},
                "Your model",
                "already set up",
                selected=True,
                listed=main_model in by_model,
            )
        )

    # Ollama: the server of the saved model, else a local one if it answers.
    server = main_url if _prefix(main_model) == "ollama" and main_url else "http://localhost:11434"
    try:
        installed = fetch_models(normalize_base_url(server))
    except (OSError, ValueError):
        installed = []
    for name in installed:
        model = f"ollama/{name}"
        if model == main_model:
            continue
        entry = by_model.get(model) or by_model.get(f"ollama_chat/{name}")
        listed_here = entry is not None
        if entry is None:
            entry = ModelCatalogEntry(
                name=_unique_name(f"{name.replace(':', '-')}-local", taken), model=model
            )
        candidates.append(
            Candidate(
                entry,
                {"name": entry.name, "base_url": normalize_base_url(server)},
                f"On {_host(server)}",
                _ratings_text(entry) if listed_here else "not in Certo's list: you rate it",
                listed=listed_here,
            )
        )

    actions: list[_Action] = []
    for provider in load_providers():
        if not provider.key_env:
            continue
        reuse_main = _prefix(main_model) == provider.id and main_key
        if (env.get(provider.key_env) or "").strip() or reuse_main:
            variable = (
                provider.key_env
                if (env.get(provider.key_env) or "").strip()
                else ("CERTO_LLM_API_KEY")
            )
            candidates.extend(_cloud_candidates(listed, provider, variable, main_model))
        else:
            actions.append(_Action(f"{provider.label} models (asks for a key)", provider))
    actions.append(_Action(_ANOTHER))
    return candidates, actions


def _cloud_candidates(
    listed: list[ModelCatalogEntry], provider, variable: str, main_model: str
) -> list[Candidate]:
    return [
        Candidate(
            entry,
            {"name": entry.name, "api_key": f"${{{variable}}}"},
            f"{provider.label} ({variable} found)",
            _ratings_text(entry),
        )
        for entry in listed
        if _prefix(entry.model) == provider.id and entry.model != main_model
    ]


def _show(prompter: Prompter, candidates: list[Candidate], actions: list[_Action]) -> None:
    group = None
    number = 0
    for candidate in candidates:
        number += 1
        if candidate.group != group:
            group = candidate.group
            prompter.say(f"  {group}")
        mark = "x" if candidate.selected else " "
        note = f"  {candidate.note}" if candidate.note else ""
        prompter.say(f"  {number:>2}. [{mark}] {candidate.entry.name}{note}")
    if actions:
        prompter.say("  More")
    for action in actions:
        number += 1
        prompter.say(f"  {number:>2}. {action.label}")


def _choose(
    prompter: Prompter,
    setup: _Setup,
    actions: list[_Action],
    listed: list[ModelCatalogEntry],
    env: dict[str, str],
) -> None:
    """Numbers toggle a model on or off, or run an action; Enter ends. On
    a real terminal, an arrow-key checklist instead."""
    if prompter.menus:
        _choose_in_menu(prompter, setup, actions, listed, env)
        return
    while True:
        prompter.say()
        _show(prompter, setup.candidates, actions)
        answer = prompter.ask("Numbers to add or remove, separated by spaces (Enter when done)")
        if not answer:
            return
        total = len(setup.candidates) + len(actions)
        picked = answer.replace(",", " ").split()
        if not all(p.isdigit() and 1 <= int(p) <= total for p in picked):
            prompter.say(f"Please enter numbers from 1 to {total}.")
            continue
        for number in sorted({int(p) for p in picked}):
            if number <= len(setup.candidates):
                candidate = setup.candidates[number - 1]
                candidate.selected = not candidate.selected
                continue
            action = actions[number - 1 - len(setup.candidates)]
            if action.provider is not None:
                _add_key(prompter, setup, actions, action, listed, env)
            else:
                _add_typed(prompter, setup, listed)


def _choose_in_menu(
    prompter: Prompter,
    setup: _Setup,
    actions: list[_Action],
    listed: list[ModelCatalogEntry],
    env: dict[str, str],
) -> None:
    while True:
        rows: list[_menus.Row] = []
        group = None
        for candidate in setup.candidates:
            if candidate.group != group:
                group = candidate.group
                rows.append(_menus.Row("header", group))
            rows.append(
                _menus.Row("item", candidate.entry.name, candidate.note, candidate.selected)
            )
        rows.append(_menus.Row("header", "More"))
        rows += [_menus.Row("action", action.label) for action in actions]
        rows.append(_menus.Row("action", "Done"))
        state = _menus.ChecklistState(rows)
        try:
            picked = _menus.checklist("Which models?", state)
        except (KeyboardInterrupt, EOFError) as exc:
            raise Cancelled from exc
        items = [row for row in rows if row.kind == "item"]
        for candidate, row in zip(setup.candidates, items, strict=True):
            candidate.selected = row.checked
        if picked is None or rows[picked].label == "Done":
            return
        action = actions[[r for r in rows if r.kind == "action"].index(rows[picked])]
        if action.provider is not None:
            _add_key(prompter, setup, actions, action, listed, env)
        else:
            _add_typed(prompter, setup, listed)


def _add_key(prompter, setup, actions, action, listed, env) -> None:
    provider = action.provider
    where = f" (get one at {provider.key_url})" if provider.key_url else ""
    key = prompter.secret(f"{provider.label} API key{where}, hidden")
    if not key:
        return
    setup.new_keys[provider.key_env] = key
    env[provider.key_env] = key
    actions.remove(action)
    setup.candidates.extend(_cloud_candidates(listed, provider, provider.key_env, ""))
    prompter.say(f"Your key will be saved in the settings file as {provider.key_env}.")


def _add_typed(prompter: Prompter, setup: _Setup, listed: list[ModelCatalogEntry]) -> None:
    model = prompter.ask("LiteLLM model id (for example openrouter/z-ai/glm-5)")
    if not model or "/" not in model:
        prompter.say("A LiteLLM model id has a provider prefix, such as openai/ or ollama/.")
        return
    personal: dict = {}
    key_env = prompter.ask(
        "The settings variable that holds its key (Enter for none, e.g. a local model)"
    )
    if key_env:
        personal["api_key"] = f"${{{key_env}}}"
    base_url = prompter.ask("Server address (Enter for the provider's default)")
    if base_url:
        personal["base_url"] = normalize_base_url(base_url)
    taken = {e.name for e in listed} | {c.entry.name for c in setup.candidates}
    name = _unique_name(model.split("/", 1)[-1].replace(":", "-").replace("/", "-"), taken)
    entry = ModelCatalogEntry(name=name, model=model)
    setup.candidates.append(
        Candidate(
            entry,
            {"name": name, **personal},
            "Typed by you",
            "not in Certo's list: you rate it",
            selected=True,
            listed=False,
        )
    )


def _ask_ratings(prompter: Prompter, candidate: Candidate, chosen: list[Candidate]) -> bool:
    """Ratings for a model the list doesn't have, next to the list's
    ratings of the other chosen models, so the scale is the same. False
    when the user leaves it out."""
    prompter.say(
        f"\n{candidate.entry.name} isn't in Certo's list. Rate it from 1 to 5 (higher is "
        "better; for cost, 5 means cheap), or answer 0 to leave it out."
    )
    known = [c for c in chosen if c.listed][:3]
    if known:
        prompter.say("For comparison, Certo's list rates:")
        for other in known:
            prompter.say(f"  {other.entry.name}: {_ratings_text(other.entry)}")
    ratings: dict[str, float] = {}
    for axis in _AXES:
        while True:
            answer = prompter.ask(f"  {axis}", "3")
            if answer.isdigit() and 0 <= int(answer) <= 5:
                break
            prompter.say("Please enter a number from 0 to 5.")
        if answer == "0":
            return False
        ratings[axis] = int(answer)
    candidate.entry = replace(candidate.entry, ratings=ratings)
    return True


def _test(
    prompter: Prompter,
    candidates: list[Candidate],
    env: Mapping[str, str],
    check: Callable[..., LLMCheckResult],
    timeout: int,
) -> list[Candidate]:
    """Test each model; return the ones that pass."""
    prompter.say("\nTesting each model with one small request:")
    working = []
    for candidate in candidates:
        values = {}
        for key in ("api_key", "base_url"):
            value = candidate.personal.get(key)
            if value and value.startswith("${") and value.endswith("}"):
                value = (env.get(value[2:-1]) or "").strip() or None
            values[key] = value
        entry = replace(candidate.entry, **values)
        result = check(entry_config(entry), timeout=timeout)
        if result.ok:
            prompter.say(f"  ok  {candidate.entry.name} ({result.latency_seconds:.1f}s)")
            working.append(candidate)
        else:
            prompter.say(f"  no  {candidate.entry.name}: {explain(result)} Left out.")
    return working


def _set_setting(path: str, name: str, value: str) -> None:
    """Set `name` in a settings file: replace its active line, else append.
    Comments go above, never to the right (python-dotenv)."""
    lines = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name and not line.lstrip().startswith("#"):
            lines[i] = f"{name}={value}"
            break
    else:
        lines += ["", f"{name}={value}"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_private(path, "\n".join(lines) + "\n")


def _unlisted_yaml(candidates: list[Candidate]) -> str:
    entries = [
        {
            "name": c.entry.name,
            "model": c.entry.model,
            "description": "Added by certo init models; rated by you.",
            "ratings": c.entry.ratings,
        }
        for c in candidates
    ]
    text = yaml.safe_dump(entries, sort_keys=False, default_flow_style=None)
    return "\n  # Added by certo init models, rated by you.\n" + "".join(
        f"  {line}\n" for line in text.splitlines()
    )


def _append_unlisted(list_path: str, unlisted: list[Candidate]) -> None:
    """Append the user-rated models at the end of the list, keeping its
    comments. The end of the file must be the `models:` list (true for the
    example and since 0.1.20); when it isn't, the file is left as it was."""
    with open(list_path, encoding="utf-8") as f:
        before = f.read()
    after = before.rstrip("\n") + "\n" + _unlisted_yaml(unlisted)
    names = {m.get("name") for m in (yaml.safe_load(after) or {}).get("models") or []}
    if not all(c.entry.name in names for c in unlisted):
        raise ModelCatalogError(
            f"Couldn't add your models to {list_path}: its last section isn't the "
            "models: list. Move the models: list to the end of the file, or add them "
            "there yourself."
        )
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(after)


def _write(
    prompter: Prompter, folder: str, settings_path: str, setup: _Setup, working: list[Candidate]
) -> tuple[str, str, str] | None:
    """Write the model files and the new keys. None when the user keeps
    an existing models.yaml."""
    models_path = os.path.join(folder, MODELS_FILE)
    list_path = find(LIST_FILE) or os.path.join(folder, LIST_FILE)
    profiles_path = find(PROFILES_FILE) or os.path.join(folder, PROFILES_FILE)
    if os.path.isfile(models_path):
        prompter.say(f"\nYou already have {models_path}.")
        if not prompter.confirm("Replace it? (the old one is kept as models.yaml.bak)"):
            return None
        shutil.copyfile(models_path, models_path + ".bak")
    os.makedirs(folder, exist_ok=True)
    written = []
    if not os.path.isfile(list_path):
        shutil.copyfile(example_path(LIST_FILE), list_path)
        save_base(list_path)  # for certo models update
        written.append(f"{LIST_FILE}  the example list")
    unlisted = [c for c in working if not c.listed]
    if unlisted:
        _append_unlisted(list_path, unlisted)
        written.append(f"{LIST_FILE}  {len(unlisted)} model(s) rated by you, added")
    if not os.path.isfile(profiles_path):
        shutil.copyfile(example_path(PROFILES_FILE), profiles_path)
        written.append(f"{PROFILES_FILE}  the example profiles")
    body = yaml.safe_dump({"models": [c.personal for c in working]}, sort_keys=False)
    header = (
        "# Written by certo init models. Keys are in the settings file\n"
        f"# ({settings_path}); this file only names them.\n"
    )
    _write_private(models_path, header + body)
    written.insert(0, f"{MODELS_FILE}  {len(working)} models")
    for name, key in setup.new_keys.items():
        _set_setting(settings_path, name, _quote(key))
    if setup.new_keys:
        written.append(f"{os.path.basename(settings_path)}  {', '.join(setup.new_keys)}")
    prompter.say(f"\nWritten to {folder}:")
    for line in written:
        prompter.say(f"  {line}")
    return list_path, models_path, profiles_path


def _preview(prompter: Prompter, paths: tuple[str, str, str], env: Mapping[str, str]) -> None:
    list_path, models_path, profiles_path = paths
    catalog = load_model_catalog(
        list_path, models_path, profiles_path=profiles_path, strict=False, environ=env
    )
    prompter.say("\nWhat --auto-model would choose:")
    for line in _profile_lines(catalog)[1:]:
        prompter.say(line)
    try:
        ladder = derive_ladder(catalog)
    except EscalationError:
        return
    rungs = " -> ".join(describe_rung(r, scores=False) for r in ladder.rungs)
    prompter.say(f"\nHow --escalate would climb: {rungs}")
    for note in ladder.skipped:
        prompter.say(f"  Left out: {note}")
    if len(ladder.rungs) == 1:
        prompter.say(
            "  With one rung --escalate can't climb: add a stronger model, or write a "
            "ladder in escalation.yaml."
        )


def _profiles_only(prompter: Prompter, folder: str, env: Mapping[str, str]) -> int:
    """`certo init models --profiles`: the profile choice alone, on the
    model files already there (the example profiles first, if none)."""
    try:
        list_path, models_path = resolve(
            env.get("CERTO_MODELS_FILE", ""), env.get("CERTO_MODELS_LIST_FILE", "")
        )
        profiles_path = find(PROFILES_FILE, env.get("CERTO_TASK_PROFILES_FILE", ""))
        if profiles_path is None:
            profiles_path = os.path.join(folder, PROFILES_FILE)
            os.makedirs(folder, exist_ok=True)
            shutil.copyfile(example_path(PROFILES_FILE), profiles_path)
            prompter.say(f"Wrote the example task profiles to {profiles_path}.")
        choose_profiles(prompter, list_path, models_path, profiles_path, env)
    except ModelCatalogError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Cancelled:
        prompter.say("\nCancelled. The choices made before are saved.")
        return 130
    prompter.say('certo check --task "..." shows which models a task would get.')
    return 0


def init_models_main(
    argv: list[str],
    *,
    prompter: Prompter | None = None,
    check: Callable[..., LLMCheckResult] = check_tool_calling,
    fetch_models: Callable[[str], list[str]] = fetch_ollama_models,
    interactive: bool | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    prompter = prompter or Prompter()
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if not interactive:
        print("Error: certo init models asks questions, so it needs a terminal.", file=sys.stderr)
        return 1
    load_settings_files()
    env = dict(os.environ)
    settings_path = user_settings_path()
    folder = os.path.dirname(settings_path)
    if args.profiles:
        return _profiles_only(prompter, folder, env)
    list_source = find(LIST_FILE) or example_path(LIST_FILE)
    try:
        listed = _parse_list(list_source)
    except ModelCatalogError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    paths = None
    try:
        prompter.say(
            "Set up more models, for --auto-model and --escalate. Nothing is written "
            "until every chosen model has been tested.\nThe models this computer can reach:"
        )
        setup = _Setup()
        setup.candidates, actions = _gather(listed, env, fetch_models, prompter)
        _choose(prompter, setup, actions, listed, env)
        chosen = [c for c in setup.candidates if c.selected]
        chosen = [c for c in chosen if c.listed or _ask_ratings(prompter, c, chosen)]
        if len(chosen) < 2:
            prompter.say(
                "\nWith fewer than two models there is nothing to choose between, so "
                "nothing was written. Your single model works as it is."
            )
            return 0
        working = _test(prompter, chosen, env, check, args.timeout)
        if len(working) < 2:
            prompter.say(
                "\nFewer than two models passed the test, so nothing was written. Fix "
                "what the lines above say, then run certo init models again."
            )
            return 1
        try:
            paths = _write(prompter, folder, settings_path, setup, working)
        except ModelCatalogError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if paths is None:
            prompter.say("Kept your models.yaml; nothing was written.")
            return 0
        _preview(prompter, paths, env)
        prompter.say()
        index = prompter.choose("Use for every run:", [label for _mode, label in _MODES])
        mode = _MODES[index][0]
        _set_setting(settings_path, "CERTO_MODEL_SELECTION", mode)
        if mode == "auto":
            choose_profiles(prompter, *paths, env)
    except Cancelled:
        if paths is None:
            prompter.say("\nCancelled. Nothing was written.")
        else:
            prompter.say(
                "\nCancelled. The model files are written; the mode for every run wasn't changed."
            )
        return 130
    prompter.say(f"\nSaved CERTO_MODEL_SELECTION={mode} in {settings_path}.")
    if mode == "manual":
        prompter.say("Add --auto-model or --escalate to a single run to use the other models.")
    prompter.say('certo check shows the files, and certo check --task "..." one task\'s models.')
    return 0
