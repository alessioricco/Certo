"""`certo models update`: slim a full copy of the model list down to the
user's own changes, so Certo's list (read from the package, the lowest
layer) gives everything else (DECISIONS.md, 2026-11-14).

For every model in the user's copy, each field (and each rating, axis by
axis) is compared with Certo's own list:

- the same as Certo's: dropped, Certo's value is read anyway;
- different, and the base the copy came from (`.models_list.base.yaml`,
  saved by `certo init models` before 0.2.3) has Certo's old value: the
  user never changed it, it is just old: dropped;
- different, and the user changed it (it differs from the base too): kept;
- different, with no base to tell: undecided, asked about (or kept, or
  dropped with --use-certos).

A model Certo's list doesn't have is the user's own and is kept whole,
unless the base had it unchanged (Certo removed it) and models.yaml
doesn't use it. Nothing here reads models.yaml's keys: only its names.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import yaml


@dataclass
class EntryPlan:
    name: str
    own: bool  # not in Certo's list: kept whole
    entry: dict  # the user's whole entry
    kept: dict = field(default_factory=dict)  # field -> value, decided to keep
    dropped: list[str] = field(default_factory=list)  # fields Certo gives now
    undecided: dict = field(default_factory=dict)  # field -> (yours, Certo's)
    remove: bool = False  # a model Certo removed, unchanged and unused


def _flatten(entry: dict) -> dict:
    """An entry's fields, with `ratings` split per axis (`ratings.code`)."""
    flat = {}
    for key, value in entry.items():
        if key == "name":
            continue
        if key == "ratings" and isinstance(value, dict):
            for axis, rating in value.items():
                flat[f"ratings.{axis}"] = rating
        else:
            flat[key] = value
    return flat


def _same(a, b) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return float(a) == float(b)
    return a == b


def _by_name(models: Iterable) -> dict[str, dict]:
    return {m["name"]: m for m in models if isinstance(m, dict) and m.get("name")}


def plan_slim(
    user_models: list[dict],
    builtin_models: list[dict],
    base_models: list[dict] | None,
    used: set[str],
) -> list[EntryPlan]:
    builtin = _by_name(builtin_models)
    base = _by_name(base_models) if base_models is not None else None
    plans = []
    for entry in user_models:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = entry["name"]
        if name not in builtin:
            removed_by_certo = (
                base is not None
                and name in base
                and _flatten(base[name]) == _flatten(entry)
                and name not in used
            )
            plans.append(EntryPlan(name, own=True, entry=entry, remove=removed_by_certo))
            continue
        plan = EntryPlan(name, own=False, entry=entry)
        certos = _flatten(builtin[name])
        origin = _flatten(base[name]) if base is not None and name in base else None
        for key, value in _flatten(entry).items():
            if key in certos and _same(value, certos[key]):
                plan.dropped.append(key)
            elif origin is not None and key in origin and _same(value, origin[key]):
                plan.dropped.append(key)  # never changed by the user: just old
            elif origin is not None:
                plan.kept[key] = value  # the user's own change
            else:
                plan.undecided[key] = (value, certos.get(key))
        plans.append(plan)
    return plans


def _unflatten(name: str, fields: dict) -> dict:
    entry: dict = {"name": name}
    ratings = {k.split(".", 1)[1]: v for k, v in fields.items() if k.startswith("ratings.")}
    for key, value in fields.items():
        if not key.startswith("ratings."):
            entry[key] = value
    if ratings:
        entry["ratings"] = ratings
    return entry


def render(plans: list[EntryPlan]) -> str | None:
    """The slimmed file, or None when nothing is left (no file needed)."""
    entries = []
    for plan in plans:
        if plan.own:
            if not plan.remove:
                entries.append(plan.entry)
            continue
        if plan.kept:
            entries.append(_unflatten(plan.name, plan.kept))
    if not entries:
        return None
    header = (
        "# Your changes to Certo's model list (which Certo reads from the\n"
        "# package): only what differs from Certo's goes here. A model given\n"
        "# here with only some fields keeps Certo's values for the others.\n"
    )
    body = yaml.safe_dump({"models": entries}, sort_keys=False, default_flow_style=None)
    return header + body
