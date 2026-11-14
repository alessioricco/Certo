"""`certo models secure`: move keys written out in full in models.yaml into
the user settings file, and name them there as `"${NAME}"`.

models.yaml already reads `${NAME}` from the settings file or the
environment (model_catalog._expand_vars); this moves an old file to that
form. The settings file is written first, so a key is never only in
memory; models.yaml keeps its comments and layout (only the key values
change), and the result is checked before it is saved. No backup of
models.yaml is kept: it would hold the keys. Nothing here prints a key.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

import yaml

from .init_cmd import _quote, load_providers
from .model_catalog import _VAR_RE


@dataclass(frozen=True)
class Move:
    """One model's key: where it goes. Never holds the key in a repr."""

    model_name: str
    variable: str
    key: str = field(repr=False)
    # True when the settings file already has this key under `variable`:
    # nothing to write, only the reference. A key only in the shell's
    # environment is still written, so runs from elsewhere find it.
    already_set: bool = False


def is_written_out(value: object) -> bool:
    """An api_key value that is a key itself, not a `${NAME}` reference."""
    return isinstance(value, str) and bool(value.strip()) and not _VAR_RE.search(value)


def _provider_variable(model_id: str) -> str:
    prefix = model_id.split("/", 1)[0] if "/" in model_id else ""
    for provider in load_providers():
        if provider.id == prefix and getattr(provider, "key_env", ""):
            return provider.key_env
    if prefix:
        return re.sub(r"[^A-Z0-9]+", "_", prefix.upper()).strip("_") + "_API_KEY"
    return ""


def _name_variable(model_name: str) -> str:
    return "CERTO_" + re.sub(r"[^A-Z0-9]+", "_", model_name.upper()).strip("_") + "_API_KEY"


def plan_moves(
    entries: list[dict],
    model_ids: Mapping[str, str],
    settings: Mapping[str, str],
    environ: Mapping[str, str],
) -> list[Move]:
    """A `Move` for every entry whose api_key is written out. `model_ids`
    maps a catalog name to its LiteLLM id (for the provider's usual
    variable). A variable that already holds a different key, in the
    settings file or the environment (which wins over the file), isn't
    reused: the model gets one of its own."""
    taken: dict[str, str] = {}  # variable -> key, decided so far
    moves: list[Move] = []
    for entry in entries:
        key = entry.get("api_key")
        name = str(entry.get("name", ""))
        if not is_written_out(key):
            continue
        key = key.strip()
        options = [v for v in (_provider_variable(model_ids.get(name, "")),) if v]
        options.append(_name_variable(name))
        for variable in options:
            current = taken.get(variable) or environ.get(variable) or settings.get(variable)
            current = (current or "").strip()
            if current and current != key:
                continue
            same_in_file = (settings.get(variable) or "").strip() == key
            moves.append(Move(name, variable, key, already_set=same_in_file))
            taken[variable] = key
            break
        else:  # the model's own variable holds another key: number it
            n = 2
            while (environ.get(f"{options[-1]}_{n}") or settings.get(f"{options[-1]}_{n}")) or (
                f"{options[-1]}_{n}" in taken
            ):
                n += 1
            variable = f"{options[-1]}_{n}"
            moves.append(Move(name, variable, key))
            taken[variable] = key
    return moves


_LINE = re.compile(r"^(?P<lead>.*?\bapi_key:[ \t]*)(?P<value>.*?)(?P<tail>[ \t]+#.*)?$")


def rewrite_models_yaml(text: str, moves: list[Move]) -> str:
    """`text` with each moved key's value replaced by `"${VARIABLE}"`,
    keeping every other line as it is. Raises ValueError when the result
    doesn't read back as the same file with references (the caller then
    leaves the file alone)."""
    by_key = {m.key: m.variable for m in moves}
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        found = _LINE.match(body)
        if not found:
            continue
        whole = found["value"] + (found["tail"] or "")
        # Without the trailing comment first, so it is kept; whole when a
        # quoted key holds " #".
        for value, tail in ((found["value"], found["tail"] or ""), (whole, "")):
            try:
                parsed = yaml.safe_load(value) if value.strip() else None
            except yaml.YAMLError:
                continue
            if isinstance(parsed, str) and parsed.strip() in by_key:
                lines[i] = f'{found["lead"]}"${{{by_key[parsed.strip()]}}}"{tail}{ending}'
                break
    result = "".join(lines)
    _check_rewrite(text, result, moves)
    return result


def _check_rewrite(before: str, after: str, moves: list[Move]) -> None:
    old = (yaml.safe_load(before) or {}).get("models", [])
    new = (yaml.safe_load(after) or {}).get("models", [])
    expected = {m.model_name: f"${{{m.variable}}}" for m in moves}
    if len(old) != len(new):
        raise ValueError("the number of models changed")
    for a, b in zip(old, new, strict=True):
        name = a.get("name") if isinstance(a, dict) else None
        want = dict(a)
        if name in expected:
            want["api_key"] = expected[name]
        if want != b:
            raise ValueError(f"the entry {name!r} would change in another way")


def rebuild_models_yaml(text: str, moves: list[Move]) -> str:
    """The fallback when a line-by-line change isn't possible (a model
    written on one line, `{name: ..., api_key: ...}`): the file rebuilt
    from its data, references in place. Comments are lost; the header
    says so."""
    data = yaml.safe_load(text) or {}
    expected = {m.model_name: f"${{{m.variable}}}" for m in moves}
    for entry in data.get("models", []):
        if isinstance(entry, dict) and entry.get("name") in expected:
            entry["api_key"] = expected[entry["name"]]
    header = (
        "# Rewritten by certo models secure: keys moved to the settings file,\n"
        "# named here as ${NAME}. Comments of the old file were not kept.\n"
    )
    result = header + yaml.safe_dump(data, sort_keys=False)
    _check_rewrite(text, result, moves)
    return result


def write_settings(path: str, moves: list[Move]) -> list[str]:
    """Add each new variable to the settings file (owner-only), comment
    above. Returns the names written."""
    from .init_models import _set_setting

    written: list[str] = []
    for move in moves:
        if move.already_set or move.variable in written:
            continue
        _set_setting(path, move.variable, _quote(move.key))
        written.append(move.variable)
    return written


def read_settings(path: str) -> dict[str, str]:
    """The settings file's values, without filling the environment."""
    if not os.path.isfile(path):
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}
