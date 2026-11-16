"""The model data file: third-party scores and prices for every model the
sources rate (DECISIONS.md, 2026-11-16).

`scripts/build_model_data.py` fetches LMArena's leaderboard dataset,
Epoch AI's benchmark data and LiteLLM's price list, and calls `build()`
here; a person reviews the diff of `data/model_data.json` before a
release. `certo models refresh` reads it back with `load()` and turns each
model's entry into ratings (ratings.py).

Models are keyed by `model_key()`, a spelling-free form of the model's
name, so `anthropic/claude-opus-5-5`, `openrouter/anthropic/claude-opus-5-5`
and LMArena's "Claude Opus 5.5 (Max)" are one model. `aliases` (reviewed
by hand) joins names the sources spell differently from the ids people
use, such as Ollama's `qwen3` for "Qwen3-8B".
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .ratings import DEFAULT_ANCHORS, Anchor, ModelData

FORMAT = 1
# The scale the anchors define. A new set of anchors is a new scale.
SCALE = "2026-11-16"

# Where each raw score comes from: LMArena table and category.
LMARENA_SCORES = {
    "lmarena_webdev": ("webdev", "overall"),
    "lmarena_text_factuality": ("text_factuality", "overall"),
}
LMARENA_TABLES = ("webdev", "text_factuality", "text", "agent")

SOURCES = (
    {
        "id": "lmarena",
        "name": "LMArena leaderboard dataset",
        "url": "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset",
        "license": "CC-BY-4.0",
    },
    {
        "id": "epoch",
        "name": "Epoch AI Benchmarking Hub (Epoch Capabilities Index)",
        "url": "https://epoch.ai/data/benchmark_data.zip",
        "license": "CC-BY-4.0",
    },
    {
        "id": "litellm",
        "name": "LiteLLM model prices",
        "url": "https://github.com/BerriAI/litellm",
        "license": "MIT",
    },
)


def model_key(name: str) -> str:
    """A model's name with its spelling taken out: lower case, no provider
    prefix, no "(Max)"-style variant, no date or `preview` suffix, and no
    separators, so "Gemma 4 31B" and `ollama/gemma4:31b` meet."""
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = s.rsplit("/", 1)[-1]
    s = re.sub(r"[ ._:/]+", "-", s).strip("-")
    s = re.sub(r"-(\d{8}|preview|it-qat|latest)$", "", s)
    return s.replace("-", "")


@dataclass
class _Entry:
    names: set[str] = field(default_factory=set)
    scores: dict[str, float] = field(default_factory=dict)
    cost_per_task: float | None = None
    cost_sessions: float = -1.0
    litellm: str | None = None
    price_in: float | None = None
    price_out: float | None = None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN is no number


def build(
    lmarena: Mapping[str, Iterable[Mapping[str, Any]]],
    eci_rows: Iterable[Mapping[str, Any]],
    prices: Mapping[str, Any],
    aliases: Mapping[str, str],
    generated: str,
    anchors: Mapping[str, Anchor] = DEFAULT_ANCHORS,
) -> dict[str, Any]:
    """The data file's content. `lmarena`: rows per table (as the
    dataset has them); `eci_rows`: Epoch's `eci_scores.csv`; `prices`:
    LiteLLM's price list. A score is the best of a model's variants
    ("(High)", "(Max)"), as benchmarks are run at high effort; the cost
    per task is the most used variant's."""
    entries: dict[str, _Entry] = {}

    def entry(name: str) -> _Entry:
        key = model_key(name)
        found = entries.setdefault(aliases.get(key, key), _Entry())
        found.names.add(name)
        return found

    def keep_best(found: _Entry, source: str, value: float | None) -> None:
        if value is not None and value > found.scores.get(source, float("-inf")):
            found.scores[source] = value

    published = ""
    for source, (table, category) in LMARENA_SCORES.items():
        for row in lmarena.get(table, ()):
            if row.get("category") == category:
                keep_best(entry(row["model_name"]), source, _number(row.get("rating")))
                published = max(published, str(row.get("leaderboard_publish_date") or ""))
    for row in lmarena.get("agent", ()):
        if row.get("category") != "overall":
            continue
        cost = _number(row.get("cost_per_task_p50"))
        sessions = _number(row.get("session_count")) or 0.0
        found = entry(row["model_name"])
        if cost is not None and sessions > found.cost_sessions:
            found.cost_per_task, found.cost_sessions = cost, sessions
    for row in eci_rows:
        keep_best(entry(row["Model"]), "epoch_eci", _number(row.get("eci")))

    # List prices for the models the sources rate: the id with the fewest
    # provider prefixes (the provider's own), then the shortest.
    for model_id in sorted(prices, key=lambda m: (m.count("/"), len(m), m)):
        info = prices[model_id]
        if not isinstance(info, dict) or info.get("mode") not in (None, "chat", "responses"):
            continue
        found = entries.get(aliases.get(model_key(model_id), model_key(model_id)))
        price_in = _number(info.get("input_cost_per_token"))
        price_out = _number(info.get("output_cost_per_token"))
        if found is None or found.litellm is not None or price_in is None or price_out is None:
            continue
        found.litellm = model_id
        found.price_in, found.price_out = round(price_in * 1e6, 4), round(price_out * 1e6, 4)

    models = {}
    for key in sorted(entries):
        found = entries[key]
        models[key] = {
            "names": sorted(found.names),
            "scores": {s: round(v, 2) for s, v in sorted(found.scores.items())},
            "cost_per_task": found.cost_per_task,
            "litellm": found.litellm,
            "price_in": found.price_in,
            "price_out": found.price_out,
        }
    return {
        "format": FORMAT,
        "scale": SCALE,
        "generated": generated,
        "lmarena_published": published,
        "sources": list(SOURCES),
        "changes": (
            "Selected and reshaped by Certo: per model, the best score of its "
            "variants on three of the sources' measures, the median cost per "
            "agent task of its most used variant, and its list price in $ per "
            "1M tokens; names joined by a normalized key."
        ),
        "anchors": {
            axis: {"source": a.source, "points": list(a.points)} for axis, a in anchors.items()
        },
        "aliases": dict(sorted(aliases.items())),
        "models": models,
    }


@dataclass(frozen=True)
class ModelDataFile:
    """A data file, read back: the anchors and each model's data."""

    scale: str
    generated: str
    anchors: dict[str, Anchor]
    aliases: dict[str, str]
    models: dict[str, dict[str, Any]]

    def lookup(self, model: str, local: bool = False) -> ModelData | None:
        """What the file knows about `model` (any id or name for it), or
        None when no source has it."""
        key = model_key(model)
        found = self.models.get(self.aliases.get(key, key))
        if found is None:
            return None
        return ModelData(
            scores=found.get("scores") or {},
            cost_per_task=found.get("cost_per_task"),
            price_in=found.get("price_in"),
            price_out=found.get("price_out"),
            local=local,
        )


def parse(text: str) -> ModelDataFile:
    data = json.loads(text)
    if data.get("format") != FORMAT:
        raise ValueError(f"unknown model data format {data.get('format')!r}")
    return ModelDataFile(
        scale=data["scale"],
        generated=data["generated"],
        anchors={
            axis: Anchor(a["source"], tuple(a["points"])) for axis, a in data["anchors"].items()
        },
        aliases=dict(data.get("aliases") or {}),
        models=dict(data["models"]),
    )


def dumps(data: Mapping[str, Any]) -> str:
    """The file's text: one key per line and sorted, so a review reads the
    diff."""
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"
