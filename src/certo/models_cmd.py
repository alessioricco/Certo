"""`certo models`: the model-file subcommands.

- `update`: slim a full copy of the model list down to your own changes
  (models_slim.py), since Certo's own list is read from the package.
- `check`: prices and cost ratings against LiteLLM's (model_price_check.py).
- `secure`: keys out of models.yaml (models_secure.py).
- `choose`: a project's own models and strategy (models_choose.py).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import TextIO

import yaml

from . import __version__
from .init_cmd import Cancelled, Prompter
from .model_catalog import LIST_FILE, MODELS_FILE, PROJECT_FILE
from .model_files import example_path, find, user_dir

BASE_FILE = ".models_list.base.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo models",
        description="Manage your model files: models_list.yaml, and the keys in models.yaml.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser(
        "update",
        help="Slim your models_list.yaml to your own changes; Certo's list gives the rest.",
        description=(
            "Certo reads its own model list from the package, so your models_list.yaml "
            "needs only what you changed. This rewrites it that way: a value the same "
            "as Certo's, or an old value you never changed, is dropped (Certo's is "
            "read); your own models and changes are kept. When Certo can't tell an "
            "old value from your change (no record of where your copy came from), it "
            "asks. The old file is kept as models_list.yaml.bak."
        ),
    )
    update.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help="Update that project's own models_list.yaml instead of the one found first.",
    )
    update.add_argument(
        "--use-certos",
        action="store_true",
        help=("Where Certo can't tell an old value from your change, use Certo's without asking."),
    )
    update.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Rewrite without asking, keeping your value wherever Certo can't tell "
            "it from an old one. Needed without a terminal."
        ),
    )
    check = sub.add_parser(
        "check",
        help="Check the prices and cost ratings of your models_list.yaml against LiteLLM's.",
        description=(
            "Compare every model of your models_list.yaml with the price list of the "
            "installed LiteLLM, without the network or any key: a cloud model id it "
            "doesn't know, a price in a description that differs from LiteLLM's, and a "
            "cost rating that isn't what its price gives. Exit code 1 when something "
            "needs a look. The other ratings come from benchmarks and aren't checked."
        ),
    )
    check.add_argument(
        "--file",
        metavar="PATH",
        default="",
        help=(
            "The models list to check. Default: CERTO_MODELS_LIST_FILE, else "
            "./models_list.yaml, else the one in your user settings folder."
        ),
    )
    check.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Set each wrong cost rating to what its price gives (the price in the "
            "description first, else LiteLLM's). Only those numbers change; the old "
            "file is kept with .bak added to its name."
        ),
    )
    secure = sub.add_parser(
        "secure",
        help="Move API keys written out in models.yaml into your settings file.",
        description=(
            "Find every api_key in models.yaml that is a key itself, not a ${NAME} "
            "reference. Each key is written to your user settings file under the "
            "provider's usual name (OPENAI_API_KEY, ANTHROPIC_API_KEY...), or a name of "
            "its own when that one already holds another key, and models.yaml names it "
            'as "${NAME}". Comments and layout of models.yaml stay. No key is printed.'
        ),
    )
    secure.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help="Secure that project's own models.yaml instead of the one found first.",
    )
    secure.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Move the keys without asking. Needed without a terminal.",
    )
    choose = sub.add_parser(
        "choose",
        help="Choose the models a project may use; Certo proposes how to pick among them.",
        description=(
            "Tick the enabled models of your models.yaml that a project may use. Certo "
            "then proposes both strategies for them, with the cost of a run of each "
            "model: an --auto-model order per kind of task (cheaper models first) and an "
            "--escalate ladder (cheapest first), and recommends one. The choice is "
            f"written to {PROJECT_FILE} at the project's top: names only, never keys. "
            "Runs in that project then use it."
        ),
    )
    choose.add_argument(
        "--project",
        metavar="NAME",
        default=".",
        help=(
            "The project, as for a run: a name in CERTO_PROJECTS_DIR, or . for the "
            "folder a run without --project works in (the default)."
        ),
    )
    choose.add_argument(
        "--use",
        metavar="NAMES",
        default="",
        help="The models, comma-separated, instead of ticking them. Needed without a terminal.",
    )
    choose.add_argument(
        "--strategy",
        choices=["auto", "escalate"],
        default=None,
        help="The strategy to write, instead of choosing. Default: the recommended one.",
    )
    choose.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Write the file without asking. Needed without a terminal.",
    )
    return parser


def _layer_file(name: str, project: str | None) -> str | None:
    """The file a command edits: with `project`, that project's own (None
    when it has none); else the top one found."""
    if not project:
        return find(name)
    path = os.path.join(_project_folder(project), name)
    return path if os.path.isfile(path) else None


def _project_folder(name: str) -> str:
    from .config import defer_llm_check, load_config, resolve_project_dir

    with defer_llm_check():
        cfg = load_config()
    if name == ".":
        return os.path.abspath(cfg.workspace)
    path = resolve_project_dir(cfg.projects_dir, name)
    if not os.path.isdir(path):
        raise ValueError(f"There is no project '{name}' in {cfg.projects_dir}.")
    return path


def _pick_models(prompter: Prompter, enabled: list, preset: set[str]) -> list[str]:
    """The models ticked, in the catalog's order. A numbered list, or an
    arrow-key checklist on a real terminal."""
    from . import menus as _menus
    from .models_choose import run_cost

    if prompter.menus:
        rows = [_menus.Row("item", m.name, run_cost(m), m.name in preset) for m in enabled]
        rows.append(_menus.Row("action", "Done"))
        try:
            _menus.checklist("Which models may this project use?", _menus.ChecklistState(rows))
        except (KeyboardInterrupt, EOFError) as exc:
            raise Cancelled from exc
        return [m.name for m, row in zip(enabled, rows, strict=False) if row.checked]
    picked = {m.name for m in enabled if m.name in preset}
    while True:
        prompter.say()
        for i, m in enumerate(enabled, 1):
            mark = "[x]" if m.name in picked else "[ ]"
            prompter.say(f"  {i:>2}. {mark} {m.name:<28} {run_cost(m)}")
        answer = prompter.ask("Numbers to tick or untick, separated by spaces (Enter when done)")
        if not answer:
            return [m.name for m in enabled if m.name in picked]
        numbers = answer.replace(",", " ").split()
        if not all(n.isdigit() and 1 <= int(n) <= len(enabled) for n in numbers):
            prompter.say(f"Please enter numbers from 1 to {len(enabled)}.")
            continue
        for n in {int(n) for n in numbers}:
            picked ^= {enabled[n - 1].name}


def _show_proposal(prompter: Prompter, proposal) -> None:
    prompter.say("\n--auto-model: the order it tries the models, per kind of task")
    for profile in proposal.profiles:
        when = (
            "when nothing else matches"
            if profile.name == "default"
            else "title has: "
            + ", ".join(profile.triggers[:4])
            + (", ..." if len(profile.triggers) > 4 else "")
        )
        prompter.say(f"  {profile.name} ({when})")
        prompter.say(f"    {' -> '.join(proposal.orders[profile.name])}")
    prompter.say("\n--escalate: the ladder, climbed when the checks fail")
    if proposal.ladder is None:
        prompter.say(f"  none: {proposal.ladder_problem}")
    else:
        prompter.say(f"  {' -> '.join(r.name for r in proposal.ladder.rungs)}")
    recommended = "--auto-model" if proposal.recommended == "auto" else "--escalate"
    prompter.say(f"\nRecommended: {recommended}, because {proposal.reason}.")


def choose_main(args: argparse.Namespace, *, prompter: Prompter, interactive: bool) -> int:
    """`certo models choose`. 0 when the file was written, 1 when not."""
    from .catalog_check import load_checked_catalog
    from .init_cmd import _write_private
    from .model_catalog import ModelCatalogError, project_use
    from .models_choose import propose, render

    try:
        folder = _project_folder(args.project)
        # The user's own files only: the project's earlier choice is what
        # is being replaced.
        catalog = load_checked_catalog(
            os.environ.get("CERTO_MODELS_FILE", ""),
            os.environ.get("CERTO_MODELS_LIST_FILE", ""),
            look_up_optional=False,
            project_dir=folder,
        )
    except (ValueError, ModelCatalogError) as exc:
        prompter.say(f"Error: {exc}")
        return 1
    enabled = [m for m in catalog.models if m.configured and m.activated]
    if len(enabled) < 2:
        prompter.say(
            "Choosing needs at least two enabled models in your models.yaml. Run certo init "
            "models to add some."
        )
        return 1
    path = os.path.join(folder, PROJECT_FILE)
    previous = set(project_use(path) or ()) if os.path.isfile(path) else set()

    if args.use:
        chosen = [n.strip() for n in args.use.split(",") if n.strip()]
        unknown = [n for n in chosen if n not in {m.name for m in enabled}]
        if unknown:
            prompter.say(
                f"Error: not an enabled model of your models.yaml: {', '.join(unknown)}. "
                f"Enabled: {', '.join(m.name for m in enabled)}."
            )
            return 1
    elif not interactive:
        prompter.say("Without a terminal, name the models with --use (and add --yes).")
        return 1
    else:
        prompter.say(f"Project folder: {folder}")
        try:
            chosen = _pick_models(prompter, enabled, previous)
        except Cancelled:
            prompter.say("\nCancelled. Nothing was written.")
            return 130
    if len(chosen) < 2:
        prompter.say("Choose at least two models: with one, no strategy is needed.")
        return 1

    proposal = propose(catalog, chosen)
    _show_proposal(prompter, proposal)
    strategy = args.strategy or proposal.recommended
    if strategy == "escalate" and proposal.ladder is None:
        prompter.say(f"Error: no ladder to climb ({proposal.ladder_problem}).")
        return 1
    if not args.yes:
        if not interactive:
            prompter.say("\nNothing was written: run it on a terminal to confirm, or add --yes.")
            return 1
        try:
            if args.strategy is None:
                options = ["--auto-model", "--escalate"]
                strategy = ("auto", "escalate")[
                    prompter.choose(
                        "Which strategy?", options, 0 if proposal.recommended == "auto" else 1
                    )
                ]
            if not prompter.confirm(f"Write {path}?"):
                prompter.say("Nothing was written.")
                return 1
        except Cancelled:
            prompter.say("\nCancelled. Nothing was written.")
            return 130
    _write_private(path, render(chosen, strategy, proposal))
    flag = "--auto-model" if strategy == "auto" else "--escalate"
    prompter.say(
        f"Written {path}. Runs in this project now use {flag} with these models (a flag "
        "or CERTO_MODEL_SELECTION still wins). Preview a task with certo check --task."
    )
    return 0


def secure_main(args: argparse.Namespace, *, prompter: Prompter, interactive: bool) -> int:
    """`certo models secure`. 0 when nothing is left to move, 1 when
    nothing was moved for another reason, 2 when there's no file."""
    from .config import user_settings_path
    from .init_cmd import _write_private
    from .model_catalog import _parse_list
    from .models_secure import (
        plan_moves,
        read_settings,
        rebuild_models_yaml,
        rewrite_models_yaml,
        write_settings,
    )

    try:
        path = (
            _layer_file(MODELS_FILE, args.project)
            if args.project
            else find(MODELS_FILE, os.environ.get("CERTO_MODELS_FILE", ""))
        )
    except ValueError as exc:
        prompter.say(f"Error: {exc}")
        return 1
    if path is None or not os.path.isfile(path):
        prompter.say(
            f"No {MODELS_FILE} found (Certo looked in the current folder and in "
            f"{user_dir()}). Nothing to do."
        )
        return 2
    try:
        text = open(path, encoding="utf-8").read()
        entries = [e for e in (yaml.safe_load(text) or {}).get("models", []) if isinstance(e, dict)]
    except (OSError, yaml.YAMLError, AttributeError) as exc:
        prompter.say(f"Error: couldn't read {path}: {type(exc).__name__}.")
        return 1
    list_path = find(LIST_FILE, os.environ.get("CERTO_MODELS_LIST_FILE", ""))
    try:
        model_ids = {e.name: e.model for e in _parse_list(list_path)} if list_path else {}
    except Exception:  # an unreadable list only costs the provider's usual names
        model_ids = {}
    settings_path = user_settings_path()
    moves = plan_moves(entries, model_ids, read_settings(settings_path), os.environ)
    if not moves:
        prompter.say(f"{path}: no key written out. Every api_key is a ${{NAME}} reference.")
        return 0
    prompter.say(f"{path}: {len(moves)} key(s) written out. They will go to {settings_path}:")
    for move in moves:
        note = " (already there)" if move.already_set else ""
        prompter.say(f"  {move.model_name:<28} -> {move.variable}{note}")
    if not args.yes:
        if not interactive:
            prompter.say("\nNothing was changed: run it on a terminal to confirm, or with --yes.")
            return 1
        try:
            if not prompter.confirm("Move them?"):
                prompter.say("Nothing was changed.")
                return 1
        except Cancelled:
            prompter.say("\nCancelled. Nothing was changed.")
            return 130
    try:
        result = rewrite_models_yaml(text, moves)
        kept = True
    except ValueError:
        try:
            result = rebuild_models_yaml(text, moves)
            kept = False
        except ValueError as exc:
            prompter.say(f"Error: {exc}. Nothing was changed.")
            return 1
    written = write_settings(settings_path, moves)
    _write_private(path, result)
    if written:
        prompter.say(f"Added to {settings_path}: {', '.join(written)}.")
    prompter.say(
        f"{path} now names them as ${{NAME}}"
        + ("." if kept else "; it was rebuilt, so its comments are gone.")
        + " Run certo check to see the models."
    )
    return 0


def check_main(args: argparse.Namespace, *, prompter: Prompter, lookup=None) -> int:
    """`certo models check`. 0 when nothing needs a look (or `--fix` fixed
    all of it), 1 otherwise, 2 when the file can't be read."""
    from .model_price_check import fix_costs, read_prices

    path = find(LIST_FILE, args.file or os.environ.get("CERTO_MODELS_LIST_FILE", ""))
    if path is None:
        prompter.say(
            f"No {LIST_FILE} to check (Certo looked in the current folder and in "
            f"{user_dir()}). Run certo init models to set up your models."
        )
        return 2
    read = (lambda t: read_prices(t, lookup)) if lookup else read_prices
    try:
        text = open(path, encoding="utf-8").read()
        rows = read(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        prompter.say(f"Error: couldn't read {path}: {exc}")
        return 2
    prompter.say(f"{path}: {len(rows)} models, against LiteLLM's price list.")
    flagged = [(r, r.problems()) for r in rows if r.problems()]
    if not flagged:
        prompter.say("Every price and cost rating agrees.")
        return 0
    for row, problems in flagged:
        prompter.say(f"  {row.name} ({row.model})")
        for problem in problems:
            prompter.say(f"    - {problem}")
    if args.fix:
        new_text, fixed, by_hand = fix_costs(text, rows)
        if fixed:
            shutil.copyfile(path, path + ".bak")
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            prompter.say(
                f"\nFixed the cost of {len(fixed)} model(s): {', '.join(fixed)}. "
                f"The old file is {os.path.basename(path)}.bak."
            )
        if by_hand:
            prompter.say(f"Change the cost of {', '.join(by_hand)} by hand.")
        if not any(r.problems() for r in read(new_text)):
            return 0
    prompter.say(
        "\nA price that differs needs a person: the provider's pricing page says which "
        "is right (LiteLLM's list can lag, and a description can be out of date)."
        + ("" if args.fix else " certo models check --fix sets each cost from its price.")
    )
    return 1


def _used_models() -> set[str]:
    """The model names models.yaml uses (names only, never keys)."""
    path = find(MODELS_FILE)
    if path is None:
        return set()
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return set()
    return {m.get("name") for m in data.get("models") or [] if isinstance(m, dict)}


def _describe(key: str, value) -> str:
    if key == "description":
        return "description"
    if key.startswith("ratings."):
        return f"{key.split('.', 1)[1]} {value}"
    return f"{key} {value}"


def update_main(
    args: argparse.Namespace,
    *,
    prompter: Prompter,
    interactive: bool,
    example: str | None = None,
) -> int:
    """`certo models update`: slim your models_list.yaml to your own changes."""
    from .models_slim import plan_slim, render

    try:
        list_path = _layer_file(LIST_FILE, getattr(args, "project", None))
    except ValueError as exc:
        prompter.say(f"Error: {exc}")
        return 1
    if list_path is None:
        prompter.say(
            f"No {LIST_FILE} of yours to update: Certo reads its own list from the "
            "package, so you don't need one. Nothing to do."
        )
        return 0
    example = example or example_path(LIST_FILE)
    base_file = os.path.join(os.path.dirname(os.path.abspath(list_path)), BASE_FILE)
    try:
        user = (yaml.safe_load(open(list_path, encoding="utf-8")) or {}).get("models") or []
        builtin = (yaml.safe_load(open(example, encoding="utf-8")) or {}).get("models") or []
        base = None
        if os.path.isfile(base_file):
            base = (yaml.safe_load(open(base_file, encoding="utf-8")) or {}).get("models") or []
    except (OSError, yaml.YAMLError, AttributeError) as exc:
        prompter.say(f"Error: couldn't read {list_path}: {exc}")
        return 1
    plans = plan_slim(user, builtin, base, _used_models())

    prompter.say(f"{list_path}, against Certo {__version__}'s own list:")
    same = [p.name for p in plans if not p.own and not p.kept and not p.undecided]
    if same:
        prompter.say(f"  Same as Certo's, or only old values ({len(same)}): read from Certo now.")
    for p in plans:
        if p.own:
            what = "removed by Certo, unused: dropped" if p.remove else "your own model: kept"
            prompter.say(f"  {p.name}: {what}")
        elif p.kept:
            changes = ", ".join(_describe(k, v) for k, v in p.kept.items())
            prompter.say(f"  {p.name}: your change kept ({changes})")
    undecided = [p for p in plans if p.undecided]
    if undecided and base is None:
        prompter.say(
            "  No record of the list your copy came from, so for these Certo can't tell "
            "your changes from old values:"
        )
    try:
        use_all = args.use_certos
        for p in undecided:
            yours = ", ".join(_describe(k, v[0]) for k, v in p.undecided.items())
            certos = ", ".join(_describe(k, v[1]) for k, v in p.undecided.items())
            prompter.say(f"  {p.name}: yours {yours}; Certo's {certos}")
            if use_all:
                choice = 1
            elif args.yes or not interactive:
                choice = 0
            else:
                choice = prompter.choose(
                    f"  {p.name}:",
                    ["Keep yours", "Use Certo's", "Use Certo's for all the rest"],
                    default=1,
                )
                use_all = choice == 2
            if choice == 0:
                p.kept.update({k: v[0] for k, v in p.undecided.items()})
            else:
                p.dropped.extend(p.undecided)
            p.undecided = {}
        if not args.yes:
            if not interactive:
                prompter.say(
                    "\nNothing was written: run it on a terminal, or with --yes (keeps "
                    "every value Certo can't tell is old) or --use-certos."
                )
                return 1
            if not prompter.confirm(f"Rewrite {list_path} with only your changes?"):
                prompter.say("Nothing was written.")
                return 1
    except Cancelled:
        prompter.say("\nCancelled. Nothing was written.")
        return 130
    result = render(plans)
    from_certo = [p.name for p in plans if not p.own and not p.kept]
    shutil.copyfile(list_path, list_path + ".bak")
    if result is None:
        os.remove(list_path)
        prompter.say(
            f"Removed {list_path}: nothing in it differs from Certo's list. The old file is "
            f"{os.path.basename(list_path)}.bak."
        )
    else:
        with open(list_path, "w", encoding="utf-8") as f:
            f.write(result)
        prompter.say(
            f"Rewrote {list_path} with only your changes. The old file is "
            f"{os.path.basename(list_path)}.bak."
        )
    if from_certo:
        prompter.say(
            f"No model is gone: the other {len(from_certo)} ({', '.join(from_certo[:4])}"
            + (", ..." if len(from_certo) > 4 else "")
            + ") still come from Certo's own list, with Certo's current values."
        )
    if os.path.isfile(base_file):
        os.remove(base_file)
    prompter.say("certo check lists every model and which file each value comes from.")
    return 0


def models_main(
    argv: list[str],
    *,
    prompter: Prompter | None = None,
    interactive: bool | None = None,
    out: TextIO | None = None,
    example: str | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    prompter = prompter or Prompter(out=out)
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if args.command == "update":
        return update_main(args, prompter=prompter, interactive=interactive, example=example)
    if args.command == "check":
        return check_main(args, prompter=prompter)
    if args.command == "secure":
        return secure_main(args, prompter=prompter, interactive=interactive)
    if args.command == "choose":
        return choose_main(args, prompter=prompter, interactive=interactive)
    return 2
