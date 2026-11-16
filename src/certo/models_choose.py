"""`certo models choose`: pick the models a project may use, and get both
strategies proposed for them, with a recommendation.

- **Auto-model:** Certo's task profiles (their trigger words), with
  each profile's `cost` weight raised above the sum of its other weights,
  so the cheaper of the chosen models go first and the expensive ones come
  last as fallbacks (the rule agreed 2026-11-14).
- **Escalation:** the ladder Certo derives from the chosen models
  (escalation.derive_ladder): cheapest first, a model dropped when another
  is at least as capable and costs no more.

Costs shown are what one run is expected to cost (run_stats.estimate_for:
the median of your own runs when there are enough, else a guess from the
price; a local model is free). No model is called; nothing is written
until the author accepts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

import yaml

from .escalation import EscalationError, ResolvedLadder, derive_ladder
from .model_catalog import (
    PROFILES_FILE,
    PROJECT_FILE,
    ModelCatalog,
    ModelCatalogEntry,
    TaskProfile,
    _parse_profiles,
    _read_section_file,
    rank_for_profile,
)
from .model_files import certo_file
from .model_pricing import is_local
from .run_stats import estimate_for

COST_AXIS = "cost"


def cost_first(weights: dict[str, float]) -> dict[str, float]:
    """`weights` with `cost` above the sum of the other axes, so a cheaper
    model always outranks a dearer one that is better by one point on
    every other axis. Unchanged when it already is."""
    others = sum(w for axis, w in weights.items() if axis != COST_AXIS)
    if weights.get(COST_AXIS, 0) > others:
        return dict(weights)
    return {**weights, COST_AXIS: float(int(others) + 1)}


def restrict(catalog: ModelCatalog, names: Iterable[str]) -> ModelCatalog:
    """`catalog` with only `names` turned on."""
    wanted = set(names)
    return replace(
        catalog,
        models=[m if m.name in wanted else replace(m, activated=False) for m in catalog.models],
    )


def example_profiles() -> list[TaskProfile]:
    path = certo_file(PROFILES_FILE)
    return _parse_profiles(_read_section_file(path, "task_profiles"), path)


@dataclass(frozen=True)
class Proposal:
    profiles: list[TaskProfile]
    # Per profile name, the chosen models in the order --auto-model tries them.
    orders: dict[str, list[str]]
    ladder: ResolvedLadder | None
    ladder_problem: str
    recommended: str  # "auto" | "escalate"
    reason: str


def propose(catalog: ModelCatalog, chosen: list[str]) -> Proposal:
    narrowed = restrict(catalog, chosen)
    # Profiles with needs pick by fit; one with only weights gets cost first.
    profiles = [
        replace(p, model=None) if p.needs else replace(p, weights=cost_first(p.weights), model=None)
        for p in example_profiles()
    ]
    orders = {p.name: [m.name for m in rank_for_profile(narrowed, p)[0]] for p in profiles}
    try:
        ladder: ResolvedLadder | None = derive_ladder(narrowed)
        problem = ""
    except EscalationError as exc:
        ladder, problem = None, str(exc)
    recommended, reason = recommend(ladder)
    return Proposal(profiles, orders, ladder, problem, recommended, reason)


def recommend(ladder: ResolvedLadder | None) -> tuple[str, str]:
    """Escalation when its first rung is much cheaper than its last (2 or
    more points of `cost`): most tasks then end on the cheap model, and
    the strong one is paid only when needed. Otherwise auto-model, which
    picks per kind of task."""
    if ladder is not None and len(ladder.rungs) >= 2:
        first, last = ladder.rungs[0], ladder.rungs[-1]
        if (
            first.cost_rating is not None
            and last.cost_rating is not None
            and first.cost_rating - last.cost_rating >= 2
        ):
            return "escalate", (
                f"the ladder starts on {first.name}, much cheaper than {last.name}: most tasks "
                f"end on the cheap model, and {last.name} is paid only when the checks fail"
            )
    return "auto", "the chosen models are close in price, so picking per kind of task fits better"


def run_cost(entry: ModelCatalogEntry) -> str:
    """One run's expected cost, in words."""
    if is_local(entry):
        return "free (local)"
    cost, measured = estimate_for(entry.model, "task", local=False)
    if cost is None:
        return "price unknown"
    if measured is not None:
        return f"about ${cost:.2f} a run (your last {measured.runs} runs)"
    return f"about ${cost:.2f} a run (a guess from the price)"


def render(chosen: list[str], strategy: str, proposal: Proposal) -> str:
    """The text of certo-models.yaml."""
    profiles = {
        p.name: {
            **({"triggers": list(p.triggers)} if p.triggers else {}),
            **({"needs": p.needs} if p.needs else {"weights": p.weights}),
        }
        for p in proposal.profiles
    }
    data: dict = {"use": chosen, "strategy": strategy, "task_profiles": profiles}
    if proposal.ladder is not None:
        data["escalation"] = {
            "ladders": {"default": [{"model": r.name} for r in proposal.ladder.rungs]}
        }
    header = (
        f"# {PROJECT_FILE}: the models this project may use, and how Certo picks\n"
        "# among them. Written by certo models choose; edit it freely, or run the\n"
        "# command again. Names only: keys stay in your models.yaml.\n"
        "#   use        the models runs in this project may use\n"
        "#   strategy   auto (--auto-model) or escalate (--escalate); a flag or\n"
        "#              CERTO_MODEL_SELECTION still wins\n"
        "#   task_profiles  --auto-model's kinds of task: what each needs; the\n"
        "#              least costly model that meets it goes first, then stronger\n"
        "#   escalation the ladder --escalate climbs, cheapest first\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, default_flow_style=None)
