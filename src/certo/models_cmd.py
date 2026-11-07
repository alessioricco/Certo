"""`certo models update`: bring your `models_list.yaml` up to date with
the example list of the installed Certo, without losing your changes.
`certo models check` (model_price_check.py): its prices and cost ratings
against LiteLLM's price list.

It is a three-way merge, per model entry: your file, the example it was
copied from (the "base", saved next to your file as
`.models_list.base.yaml` when Certo copies the example), and the new
example. Certo's changes (new models, changed ids or ratings, models
removed from the example) are offered; your changes (a model you added,
an entry you edited) are kept. An entry both changed is asked about.
Without a base (a list copied by hand, or before 0.1.21), every entry
that differs from the example is asked about, since Certo can't tell who
changed it.

The file is edited as text, one entry block at a time (an entry starts at
`  - name:` and its fields are indented below it), so your comments and
layout stay. Before writing, the result is parsed and compared with what
was meant; on any mismatch nothing is written. The old file is kept as
`models_list.yaml.bak`.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from typing import TextIO

import yaml

from . import __version__
from .init_cmd import Cancelled, Prompter
from .model_catalog import LIST_FILE, MODELS_FILE
from .model_files import example_path, find, user_dir

BASE_FILE = ".models_list.base.yaml"
_ENTRY_START = re.compile(r"^  - name:\s*([^\s#]+)")


def base_path(list_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(list_path)), BASE_FILE)


def save_base(list_path: str, example: str | None = None) -> None:
    """Keep the example `list_path` was copied from, for the next update."""
    shutil.copyfile(example or example_path(LIST_FILE), base_path(list_path))


# --- reading entries -------------------------------------------------------------


@dataclass(frozen=True)
class _Block:
    name: str
    start: int  # first line index
    end: int  # one past the last line
    text: str


def _blocks(text: str) -> dict[str, _Block]:
    """Every entry block of a models list, by name. An entry is its
    `  - name:` line and the lines indented four or more spaces right after
    it."""
    lines = text.splitlines(keepends=True)
    blocks: dict[str, _Block] = {}
    i = 0
    while i < len(lines):
        match = _ENTRY_START.match(lines[i])
        if not match:
            i += 1
            continue
        start = i
        i += 1
        while i < len(lines) and lines[i].startswith("    ") and lines[i].strip():
            i += 1
        name = match.group(1).strip("'\"")
        blocks[name] = _Block(name, start, i, "".join(lines[start:i]))
    return blocks


def _entries(text: str) -> dict[str, dict]:
    data = yaml.safe_load(text) or {}
    models = data.get("models") if isinstance(data, dict) else None
    return {m["name"]: m for m in models or [] if isinstance(m, dict) and "name" in m}


def _differences(old: dict, new: dict) -> list[str]:
    """Plain lines saying what changed from `old` to `new`."""
    lines = []
    for key in sorted(set(old) | set(new), key=lambda k: (k != "model", k != "ratings", k)):
        if key == "name" or old.get(key) == new.get(key):
            continue
        if key == "ratings" and isinstance(old.get(key), dict) and isinstance(new.get(key), dict):
            for axis in sorted(set(old[key]) | set(new[key])):
                a, b = old[key].get(axis), new[key].get(axis)
                if a != b:
                    lines.append(f"ratings: {axis} {_show(a)} -> {_show(b)}")
        elif key == "description":
            lines.append("description changed")
        else:
            lines.append(f"{key}: {_show(old.get(key))} -> {_show(new.get(key))}")
    return lines


def _show(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# --- the plan --------------------------------------------------------------------


@dataclass
class Change:
    """One proposed change to the user's file. `kind` is "new", "changed",
    "removed" or "both" (changed in the example and by the user)."""

    kind: str
    name: str
    details: list[str]
    yours: dict | None = None
    theirs: dict | None = None


def plan(
    user_text: str, base_text: str | None, example_text: str, used: set[str]
) -> tuple[list[Change], list[str]]:
    """The changes to offer, and notes about what is kept as it is."""
    user, example = _entries(user_text), _entries(example_text)
    base = _entries(base_text) if base_text is not None else None
    changes: list[Change] = []
    notes: list[str] = []
    for name, theirs in example.items():
        yours = user.get(name)
        before = base.get(name) if base is not None else None
        if yours is None:
            if base is not None and before is not None:
                notes.append(f"{name}: removed by you, not added again")
            else:
                changes.append(Change("new", name, [theirs.get("model", "")], None, theirs))
            continue
        if yours == theirs:
            continue
        if base is None:
            changes.append(
                Change("both", name, _differences(yours, theirs), yours, theirs)
            )  # no base: who changed it is unknown
        elif before == theirs:
            notes.append(f"{name}: your changes")
        elif before == yours or before is None:
            changes.append(Change("changed", name, _differences(yours, theirs), yours, theirs))
        else:
            changes.append(Change("both", name, _differences(yours, theirs), yours, theirs))
    for name, yours in user.items():
        if name in example:
            continue
        if base is not None and name in base:
            if name in used:
                notes.append(f"{name}: no longer in the example, but models.yaml uses it")
            elif base[name] != yours:
                notes.append(f"{name}: no longer in the example, but you changed it")
            else:
                changes.append(Change("removed", name, [yours.get("model", "")], yours, None))
        else:
            notes.append(f"{name}: yours")
    return changes, notes


# --- applying --------------------------------------------------------------------


def apply(user_text: str, example_text: str, accepted: list[Change]) -> str:
    """`user_text` with the accepted changes, as text. Raises ValueError
    when the file can't be edited safely (nothing must then be written)."""
    yours, theirs = _blocks(user_text), _blocks(example_text)
    lines = user_text.splitlines(keepends=True)
    replace_at: dict[int, tuple[int, str]] = {}
    for change in accepted:
        if change.kind == "new":
            continue
        block = yours.get(change.name)
        if block is None:
            raise ValueError(f"couldn't find the entry {change.name!r} in your file")
        new_text = "" if change.kind == "removed" else theirs[change.name].text
        replace_at[block.start] = (block.end, new_text)
    new = [c for c in accepted if c.kind == "new"]
    # New entries go right after the last entry of the models list, which
    # isn't always the end of the file (a list from before 0.1.20 still has
    # its task_profiles: and escalation: sections after it).
    insert_at = max((b.end for b in yours.values()), default=len(lines))
    addition = ""
    if new:
        addition = f"\n  # Added by certo models update ({__version__}).\n" + "".join(
            theirs[c.name].text for c in new
        )
    out: list[str] = []
    i = 0
    while i <= len(lines):
        if i >= insert_at and addition:
            out.append(addition)
            addition = ""
        if i == len(lines):
            break
        if i in replace_at:
            end, new_text = replace_at[i]
            out.append(new_text)
            i = end
            # A removed entry's blank separator goes with it.
            if not new_text and i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(lines[i])
        i += 1
    result = "".join(out)
    _check(user_text, result, accepted)
    return result


def _check(before: str, after: str, accepted: list[Change]) -> None:
    """The edited file must hold exactly the intended entries."""
    expected = dict(_entries(before))
    for change in accepted:
        if change.kind == "removed":
            expected.pop(change.name, None)
        else:
            expected[change.name] = change.theirs
    try:
        got = _entries(after)
    except yaml.YAMLError as exc:
        raise ValueError(f"the result wouldn't be valid YAML ({exc})") from exc
    if got != expected:
        wrong = sorted(n for n in set(got) | set(expected) if got.get(n) != expected.get(n))
        raise ValueError(f"the result wouldn't match the plan for: {', '.join(wrong)}")


# --- the command -----------------------------------------------------------------


_LABELS = {
    "new": "New",
    "changed": "Changed",
    "removed": "Removed",
    "both": "Both changed",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo models",
        description="Manage your list of models (models_list.yaml).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser(
        "update",
        help="Bring your models_list.yaml up to date with this Certo's example list.",
        description=(
            "Compare your models_list.yaml with the example list of the installed "
            "Certo and offer each change: new models, changed ids or ratings, models "
            "removed from the example. Your own models and your edits are kept; an "
            "entry both you and the example changed is asked about. Comments and "
            "layout stay; the old file is kept as models_list.yaml.bak."
        ),
    )
    update.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Apply every change without asking, keeping your version of an entry "
            "both changed. Needed without a terminal."
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
    return parser


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
    path = find(MODELS_FILE)
    if path is None:
        return set()
    try:
        return set(_entries(open(path, encoding="utf-8").read()))
    except (OSError, yaml.YAMLError):
        return set()


def _say_change(prompter: Prompter, change: Change) -> None:
    prompter.say(f"  {_LABELS[change.kind]:<13} {change.name}")
    for line in change.details:
        if line:
            prompter.say(f"                {line}")


def update_main(
    args: argparse.Namespace,
    *,
    prompter: Prompter,
    interactive: bool,
    example: str | None = None,
) -> int:
    list_path = find(LIST_FILE)
    if list_path is None:
        prompter.say(
            f"No {LIST_FILE} to update (Certo looked in the current folder and in "
            f"{user_dir()}). Run certo init models to set up your models."
        )
        return 1
    example = example or example_path(LIST_FILE)
    user_text = open(list_path, encoding="utf-8").read()
    example_text = open(example, encoding="utf-8").read()
    base_file = base_path(list_path)
    base_text = open(base_file, encoding="utf-8").read() if os.path.isfile(base_file) else None
    try:
        changes, notes = plan(user_text, base_text, example_text, _used_models())
    except (yaml.YAMLError, AttributeError) as exc:
        prompter.say(f"Error: couldn't read {list_path}: {exc}")
        return 1

    prompter.say(f"{list_path}, against the example list of certo {__version__}:")
    if base_text is None:
        prompter.say(
            "  (No record of the example your file came from, so every entry that "
            "differs is asked about.)"
        )
    for note in notes:
        prompter.say(f"  Kept          {note}")
    if not changes:
        prompter.say("Nothing to update.")
        save_base(list_path, example)
        return 0
    for change in changes:
        _say_change(prompter, change)

    try:
        accepted = _decide(prompter, changes, interactive=interactive, yes=args.yes)
    except Cancelled:
        prompter.say("\nCancelled. Nothing was written.")
        return 130
    if accepted is None:
        prompter.say(
            "\nNothing was written: run certo models update on a terminal to choose, or "
            "with --yes to apply every change and keep your version of entries both changed."
        )
        return 0
    if not accepted:
        prompter.say("Nothing was written.")
        return 0
    try:
        result = apply(user_text, example_text, accepted)
    except ValueError as exc:
        prompter.say(
            f"\nError: {exc}. Nothing was written; the file's layout is probably not "
            "the example's. Apply the changes by hand, or start again with certo init "
            "models."
        )
        return 1
    shutil.copyfile(list_path, list_path + ".bak")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(result)
    save_base(list_path, example)
    prompter.say(
        f"\nUpdated {list_path}: {len(accepted)} change(s). The old file is "
        f"{os.path.basename(list_path)}.bak. Run certo check to see the result."
    )
    return 0


def _decide(
    prompter: Prompter, changes: list[Change], *, interactive: bool, yes: bool
) -> list[Change] | None:
    """The changes to apply. None: nothing was decided (no terminal)."""
    plain = [c for c in changes if c.kind != "both"]
    both = [c for c in changes if c.kind == "both"]
    if yes:
        return plain
    if not interactive:
        return None
    accepted: list[Change] = []
    if plain:
        prompter.say()
        options = [f"All {len(plain)}", "One by one", "None"]
        index = prompter.choose(f"Apply the {len(plain)} change(s) from the example?", options)
        if index == 0:
            accepted = list(plain)
        elif index == 1:
            accepted = [c for c in plain if prompter.confirm(f"{_LABELS[c.kind]}: {c.name}?")]
    for change in both:
        prompter.say(f"\n{change.name} differs from the example:")
        for line in change.details:
            prompter.say(f"  {line}  (yours -> the example's)")
        if not prompter.confirm("Take the example's version? (No keeps yours)"):
            continue
        accepted.append(change)
    return accepted


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
    return 2
