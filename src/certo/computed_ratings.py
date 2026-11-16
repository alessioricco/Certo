"""`certo models refresh`: ratings computed from the model data file, kept
in `ratings.yaml` in the user's Certo folder (DECISIONS.md, 2026-11-16).

Refresh reads the newest model data (a GitHub Release's file, cached, or
the one in the package), the current list prices (LiteLLM's price list,
else the installed LiteLLM's), and the user's own runs (`run_stats.csv`),
then rates every model of the model list as the folder sees it
(ratings.py) and writes them. A run reads that file as a layer: above
Certo's hand ratings, below anything the user's own `models_list.yaml` or
`models.yaml` says, which always wins (model_catalog._read_mapping). No
`ratings.yaml`, no change: the hand ratings stay until the user refreshes.

Own results move only `code` for now, from the share of task runs that
ended `verified` among those whose verdict judges the work (a run that hit
the time or cost limit, was interrupted or couldn't be checked doesn't
count): outside the benchmark, a run can't tell real work from
work that fooled the checks, so precision waits.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import yaml

from .config import user_settings_path
from .model_data import ModelDataFile, parse
from .model_pricing import is_local_model, litellm_price
from .ratings import ModelData, Rated, rate

RATINGS_FILE = "ratings.yaml"
DATA_FILE = "model_data.json"
LATEST_DATA_URL = "https://github.com/alessioricco/certo/releases/latest/download/model_data.json"
LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
FETCH_TIMEOUT_SECONDS = 20
OWN_KINDS = ("task", "milestone", "bench")
# The verdicts that judge the model's work. The others measure a limit
# (time, cost), an interrupt or checks that couldn't decide, not the model.
OWN_FAILURES = frozenset(
    {
        "failed",
        "retry_exhausted",
        "no_progress",
        "timed_out",
        "acceptance_failed",
        "independent_failed",
        "stuck",
        "unchanged",
    }
)
AXES = ("code", "reasoning", "precision", "writing", "cost", "speed")

Opener = Callable[[str], bytes]


def _open(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "certo"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read()


def ratings_path(environ: Mapping[str, str] | None = None) -> str:
    """`ratings.yaml` in the user's Certo folder (beside the settings file)."""
    return os.path.join(os.path.dirname(user_settings_path(environ)), RATINGS_FILE)


def data_cache_path(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    xdg = (environ.get("XDG_CACHE_HOME") or "").strip()
    base = xdg if os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "certo", DATA_FILE)


def shipped_data() -> ModelDataFile:
    return parse(files("certo").joinpath("data", DATA_FILE).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class DataSource:
    data: ModelDataFile
    where: str  # "the latest release", "cached from a release", "this Certo version"
    note: str = ""  # why the network wasn't used, when it wasn't


def newest_data(cache: str, opener: Opener | None) -> DataSource:
    """The newest model data: the latest release's file (fetched into the
    cache when `opener` is given), else the cache, else the package's."""
    shipped = shipped_data()
    note = ""
    fetched = False
    if opener is not None:
        try:
            text = opener(LATEST_DATA_URL).decode("utf-8")
            parse(text)  # refuse a file this Certo can't read before keeping it
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(cache + ".tmp", cache)
            fetched = True
        except urllib.error.HTTPError as exc:
            note = (
                "the latest release has no model data yet"
                if exc.code == 404
                else f"couldn't fetch the latest model data (HTTP {exc.code})"
            )
        except Exception as exc:  # noqa: BLE001 - no data online means the local copy
            note = f"couldn't fetch the latest model data ({type(exc).__name__})"
    try:
        with open(cache, encoding="utf-8") as f:
            cached = parse(f.read())
    except (OSError, ValueError, KeyError):
        cached = None
    if cached is not None and cached.generated > shipped.generated:
        return DataSource(cached, "the latest release" if fetched else "a cached release", note)
    return DataSource(shipped, "this Certo version", note)


def fetch_prices(opener: Opener | None) -> tuple[Mapping[str, Any] | None, str]:
    """LiteLLM's current price list, or None and why not."""
    if opener is None:
        return None, "offline"
    try:
        prices = json.loads(opener(LITELLM_PRICES_URL).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - the installed LiteLLM's prices then
        return None, f"couldn't fetch LiteLLM's prices ({type(exc).__name__})"
    return (prices, "") if isinstance(prices, dict) else (None, "LiteLLM's prices didn't read")


def list_price(model: str, prices: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """(input, output) $ per 1M tokens: the fetched list first, then the
    installed LiteLLM's."""
    for key in (model, model.split("/", 1)[-1]):
        info = (prices or {}).get(key)
        if isinstance(info, dict) and info.get("input_cost_per_token") is not None:
            return (
                round(float(info["input_cost_per_token"]) * 1e6, 4),
                round(float(info.get("output_cost_per_token") or 0) * 1e6, 4),
            )
    return litellm_price(model)


def own_results(rows: Iterable[Mapping[str, str]]) -> dict[str, tuple[float, int]]:
    """Per model id: the code rating its own runs point to (1 + 4 × the
    share that ended verified) and how many runs that rests on. Only runs
    whose verdict judges the work count (verified, or one of
    `OWN_FAILURES`)."""
    counts: dict[str, list[int]] = {}
    for row in rows:
        if row.get("kind") not in OWN_KINDS or not row.get("model"):
            continue
        if row.get("verdict") != "verified" and row.get("verdict") not in OWN_FAILURES:
            continue
        seen = counts.setdefault(row["model"], [0, 0])
        seen[0] += row.get("verdict") == "verified"
        seen[1] += 1
    return {model: (1 + 4 * verified / runs, runs) for model, (verified, runs) in counts.items()}


@dataclass(frozen=True)
class Refreshed:
    name: str
    model: str
    rated: Rated
    price: tuple[float, float] | None  # $ per 1M tokens, in and out
    local: bool


def compute(
    entries: Sequence[Any],
    data: ModelDataFile,
    own: Mapping[str, tuple[float, int]],
    prices: Mapping[str, Any] | None,
) -> list[Refreshed]:
    """Rate every model: `entries` have `name`, `model` and `base_url`."""
    out = []
    for entry in entries:
        local = is_local_model(entry.model, getattr(entry, "base_url", None))
        found = data.lookup(entry.model, local=local) or ModelData(local=local)
        price = None if local else list_price(entry.model, prices)
        if price is None and found.price_in is not None and found.price_out is not None:
            price = (found.price_in, found.price_out)
        if price is not None:
            found = ModelData(
                scores=found.scores,
                cost_per_task=found.cost_per_task,
                price_in=price[0],
                price_out=price[1],
                local=local,
            )
        mine = {"code": own[entry.model]} if entry.model in own else None
        out.append(
            Refreshed(entry.name, entry.model, rate(found, data.anchors, mine), price, local)
        )
    return out


def render(rows: Sequence[Refreshed], source: DataSource, today: str) -> str:
    """`ratings.yaml`'s text."""
    header = (
        f"# Written by `certo models refresh` on {today}, from Certo's model data of\n"
        f"# {source.data.generated} (LMArena and Epoch AI, CC-BY-4.0; LiteLLM prices, MIT).\n"
        "# Don't edit it: run the refresh again. To change a rating, give it in your\n"
        "# models_list.yaml or models.yaml, which always win. Delete this file to go\n"
        "# back to the ratings in Certo's model list.\n"
    )
    body = {
        "refreshed": today,
        "data": source.data.generated,
        "models": [
            {
                "name": row.name,
                "model": row.model,
                **({"no_data": True} if row.rated.no_data else {}),
                "ratings": {a: row.rated.ratings[a] for a in AXES if a in row.rated.ratings},
                "from": {a: row.rated.sources[a] for a in AXES if a in row.rated.sources},
                **({"price": list(row.price)} if row.price else {}),
            }
            for row in rows
        ],
    }
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


@dataclass(frozen=True)
class Computed:
    model: str
    ratings: dict[str, float]
    sources: dict[str, str] = field(default_factory=dict)
    no_data: bool = False


@dataclass(frozen=True)
class RatingsFile:
    """`ratings.yaml`, read back: when it was written, from which data."""

    path: str
    refreshed: str
    data: str
    models: dict[str, Computed]


def read_ratings_file(path: str | None = None) -> RatingsFile | None:
    """The file a refresh wrote, or None without a readable one."""
    path = path or ratings_path()
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        models = {}
        for entry in raw.get("models") or []:
            ratings = {str(k): float(v) for k, v in (entry.get("ratings") or {}).items()}
            sources = {str(k): str(v) for k, v in (entry.get("from") or {}).items()}
            models[str(entry["name"])] = Computed(
                str(entry["model"]), ratings, sources, bool(entry.get("no_data"))
            )
        return RatingsFile(
            path, str(raw.get("refreshed") or ""), str(raw.get("data") or ""), models
        )
    except (OSError, yaml.YAMLError, AttributeError, KeyError, TypeError, ValueError):
        return None


def read_computed(path: str | None = None) -> dict[str, Computed]:
    """The ratings a refresh wrote, by model name; {} without a readable file."""
    found = read_ratings_file(path)
    return found.models if found is not None else {}


OLD_DATA_DAYS = 60


def age_notes(found: RatingsFile, shipped: str, today_: str) -> list[str]:
    """What `certo check` says about the data's age: older than
    `OLD_DATA_DAYS`, or older than the data this Certo version ships."""
    notes = []
    if shipped > found.data:
        notes.append(
            f"this Certo version has newer model data ({shipped}): run certo models refresh"
        )
    try:
        days = (datetime.fromisoformat(today_) - datetime.fromisoformat(found.data)).days
    except ValueError:
        return notes
    if days > OLD_DATA_DAYS:
        notes.append(f"the model data is {days} days old: run certo models refresh for newer data")
    return notes


def origin(name: str, ratings: Mapping[str, float], found: RatingsFile | None) -> str:
    """Where one model's ratings come from, in a few words: computed, with
    the user's own runs; Certo's (no data); or the user's own overrides."""
    computed = found.models.get(name) if found is not None else None
    if computed is None:
        return "Certo's"
    if computed.no_data:
        kept = "Certo's (no data)"
        yours = [
            a for a in ("cost", "speed") if a in ratings and ratings[a] != computed.ratings.get(a)
        ]
        return kept + (f"; yours for {', '.join(yours)}" if yours else "")
    parts = ["computed"]
    runs = computed.sources.get("code", "")
    if "own results" in runs:
        parts.append("code with your " + runs.split("own results (", 1)[1].rstrip(")"))
    hand = [a for a in AXES if a in ratings and a not in computed.ratings]
    if hand:
        parts.append(f"Certo's for {', '.join(hand)}")
    yours = [
        a
        for a in AXES
        if a in computed.ratings and a in ratings and ratings[a] != computed.ratings[a]
    ]
    if yours:
        parts.append(f"yours for {', '.join(yours)}")
    return "; ".join(parts)


def apply_computed(
    raw: dict, user_ratings: Mapping[str, Mapping[str, float]], path: str | None = None
) -> dict:
    """Certo's model list (merged with the user's layers) with the
    computed ratings put in: on a model of the same name and id, every
    computed axis replaces Certo's, and the user's own axes still win."""
    computed = read_computed(path)
    if not computed or not isinstance(raw.get("models"), list):
        return raw
    models = []
    for entry in raw["models"]:
        found = computed.get(entry.get("name")) if isinstance(entry, dict) else None
        if found is not None and found.model == entry.get("model"):
            entry = {
                **entry,
                "ratings": {
                    **(entry.get("ratings") or {}),
                    **found.ratings,
                    **user_ratings.get(entry["name"], {}),
                },
            }
        models.append(entry)
    return {**raw, "models": models}


def changes(before: Mapping[str, Mapping[str, float]], rows: Sequence[Refreshed]) -> list[str]:
    """What moved since `before` (the last refresh, else Certo's list), by
    0.5 or more, so noise doesn't fill the screen."""
    out = []
    for row in rows:
        old = before.get(row.name) or {}
        moves = [
            f"{axis} {old[axis]:g} → {value:g}"
            for axis, value in row.rated.ratings.items()
            if axis in old and abs(old[axis] - value) >= 0.5
        ]
        if moves:
            out.append(f"{row.name}: " + ", ".join(moves))
    return out


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
