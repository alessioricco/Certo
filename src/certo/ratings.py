"""Ratings computed from third-party data (DECISIONS.md, 2026-11-16).

`rate()` turns one model's raw scores into 1-5 ratings, one decimal, on a
fixed scale: code, reasoning and precision each read one source and map
it through fixed anchor points (a straight line between them, capped at
1 and 5). Writing is the mean of reasoning and precision: no source
measures the writing Certo needs (READMEs, docs, messages).
Cost comes from the real cost per agent task where a model has one, else
from its list price; speed is only cloud (4) or local (2). A local model
loses a point on the capability axes, as it runs quantized with a short
context window, until the user's own results say otherwise. Own results
shrink in: `computed + (observed - computed) * n / (n + 5)`, moved by at
most one point.

Pure: no network, no files. The data (raw scores, anchors) comes from the
data file the maintainer script writes (TODO.md, item C); the user's own
results from `certo models refresh`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .model_pricing import cost_rating

CAPABILITY_AXES = ("code", "reasoning", "precision", "writing")
LOCAL_PENALTY = 1.0
LOCAL_SPEED = 2.0
CLOUD_SPEED = 4.0
LOCAL_COST = 5.0
SHRINK_RUNS = 5  # own runs that count as much as the computed rating
MAX_ADJUSTMENT = 1.0


@dataclass(frozen=True)
class Anchor:
    """Which raw score an axis reads, and the score that means 1, 2, 3, 4
    and 5 (rising)."""

    source: str
    points: Sequence[float]

    def rating(self, score: float) -> float:
        points = list(self.points)
        if score <= points[0]:
            return 1.0
        if score >= points[-1]:
            return float(len(points))
        for i in range(len(points) - 1):
            low, high = points[i], points[i + 1]
            if score <= high:
                return i + 1 + (score - low) / (high - low)
        return float(len(points))  # unreachable: score < points[-1]


# The anchors agreed on 2026-11-16, from LMArena's and Epoch AI's data of
# that day. The maintainer script writes them into the data file; a new
# set means a new scale version there.
DEFAULT_ANCHORS: dict[str, Anchor] = {
    "code": Anchor("lmarena_webdev", (1350, 1450, 1550, 1650, 1750)),
    "reasoning": Anchor("epoch_eci", (135, 145, 155, 162, 168)),
    "precision": Anchor("lmarena_text_factuality", (1350, 1400, 1450, 1480, 1510)),
}
# Derived from other axes, never from a source: their mean.
DERIVED = {"writing": ("reasoning", "precision")}


@dataclass(frozen=True)
class ModelData:
    """What the data file knows about one model. Every field is optional:
    a model has the scores its sources publish."""

    scores: Mapping[str, float] = field(default_factory=dict)  # source -> raw score
    cost_per_task: float | None = None  # median $ per agent task (LMArena)
    price_in: float | None = None  # list price, $ per 1M input tokens
    price_out: float | None = None  # $ per 1M output tokens
    local: bool = False


@dataclass(frozen=True)
class Rated:
    """A model's ratings, and where each came from."""

    ratings: dict[str, float]
    sources: dict[str, str]  # axis -> what it was computed from
    missing: tuple[str, ...]  # axes no source rates

    @property
    def no_data(self) -> bool:
        return all(axis in self.missing for axis in CAPABILITY_AXES)


def task_cost_rating(dollars: float) -> float:
    """Cost from the median dollars per agent task: 3 - log2($)/2, kept
    between 1 and 4.9 (each doubling takes half a point; $1 is 3)."""
    if dollars <= 0:
        return 4.9
    return round(min(4.9, max(1.0, 3 - math.log2(dollars) / 2)), 1)


def rate(
    data: ModelData,
    anchors: Mapping[str, Anchor],
    own: Mapping[str, tuple[float, int]] | None = None,
) -> Rated:
    """The 1-5 ratings for one model. `own`: per axis, the rating the
    user's own runs point to and how many runs it rests on."""
    ratings: dict[str, float] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []
    for axis, anchor in anchors.items():
        score = data.scores.get(anchor.source)
        if score is None:
            missing.append(axis)
            continue
        value = anchor.rating(score)
        source = anchor.source
        if data.local and axis in CAPABILITY_AXES:
            value = max(1.0, value - LOCAL_PENALTY)
            source += ", local −1"
        ratings[axis], sources[axis] = value, source
    for axis, parts in DERIVED.items():
        if all(part in ratings for part in parts):
            ratings[axis] = sum(ratings[part] for part in parts) / len(parts)
            sources[axis] = "mean of " + " and ".join(parts)
        else:
            missing.append(axis)

    if data.local:
        ratings["cost"], sources["cost"] = LOCAL_COST, "local"
    elif data.cost_per_task is not None:
        ratings["cost"] = task_cost_rating(data.cost_per_task)
        sources["cost"] = "cost per agent task"
    elif data.price_in is not None and data.price_out is not None:
        ratings["cost"] = cost_rating(data.price_in, data.price_out)
        sources["cost"] = "list price"
    else:
        missing.append("cost")
    ratings["speed"] = LOCAL_SPEED if data.local else CLOUD_SPEED
    sources["speed"] = "local" if data.local else "cloud"

    for axis, (observed, runs) in (own or {}).items():
        if axis not in ratings or runs <= 0:
            continue
        computed = ratings[axis]
        shift = (observed - computed) * runs / (runs + SHRINK_RUNS)
        shift = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, shift))
        ratings[axis] = min(5.0, max(1.0, computed + shift))
        sources[axis] += f", own results ({runs} run{'' if runs == 1 else 's'})"

    return Rated(
        ratings={axis: round(value, 1) for axis, value in ratings.items()},
        sources=sources,
        missing=tuple(missing),
    )
