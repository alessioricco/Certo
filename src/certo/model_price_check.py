"""`certo models check`: the prices and `cost` ratings of a models list,
against the price list of the installed LiteLLM. No network, no model
call, and no key: only `models_list.yaml` is read, never `models.yaml`.

For each model it reports what a person should look at:

- a cloud model id LiteLLM's price list doesn't know (often a misspelled
  or retired id, or a model newer than the installed LiteLLM);
- a price in the description that differs from LiteLLM's;
- a `cost` rating that isn't what its price gives (the rubric in
  `models_list.yaml.example`: `model_pricing.cost_rating`).

The other ratings (reasoning, precision, code) come from benchmarks and
judgment, so they are not checked here: see CONTRIBUTING.md, "Check the
example model list".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from .model_pricing import cost_rating, described_price, is_local_model_id, litellm_price

LOCAL_COST = 5.0


@dataclass(frozen=True)
class ModelPrices:
    """One model of the list, with what is known about its price."""

    name: str
    model: str
    local: bool
    cost: float | None  # its `cost` rating, None when it has none
    described: tuple[float, float] | None  # the price in its description
    litellm: tuple[float, float] | None  # the price in LiteLLM's list

    @property
    def expected_cost(self) -> float | None:
        """The `cost` its price gives: the described price first (the one
        the list is rated at), else LiteLLM's. None when neither is known."""
        if self.local:
            return LOCAL_COST
        price = self.described or self.litellm
        return cost_rating(*price) if price else None

    def problems(self) -> list[str]:
        if self.local:
            if self.cost is not None and self.cost != LOCAL_COST:
                return [f"cost {self.cost:g}, but a local model is free: 5"]
            return []
        found = []
        if self.litellm is None:
            found.append("not in LiteLLM's price list: check the id")
        if self.described is None:
            found.append('no "$X in / $Y out" price in its description')
        elif self.litellm is not None and not _same(self.described, self.litellm):
            found.append(
                f"price {_price(self.described)} in its description, "
                f"{_price(self.litellm)} in LiteLLM's list"
            )
        expected = self.expected_cost
        if expected is not None and self.cost != expected:
            have = "no cost rating" if self.cost is None else f"cost {self.cost:g}"
            found.append(f"{have}, its price gives {expected:g}")
        return found


def _same(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b, strict=True))


def _price(price: tuple[float, float]) -> str:
    return f"${price[0]:g} / ${price[1]:g}"


def read_prices(
    text: str,
    lookup: Callable[[str], tuple[float, float] | None] = litellm_price,
) -> list[ModelPrices]:
    """Every model of a models list, with its prices. Raises ValueError for
    a file that isn't a models list."""
    data = yaml.safe_load(text)
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        raise ValueError("no `models:` list")
    rows = []
    for entry in models:
        if not isinstance(entry, dict) or "name" not in entry or "model" not in entry:
            continue
        model = str(entry["model"])
        local = is_local_model_id(model)
        ratings = entry.get("ratings") if isinstance(entry.get("ratings"), dict) else {}
        cost = ratings.get("cost")
        rows.append(
            ModelPrices(
                name=str(entry["name"]),
                model=model,
                local=local,
                cost=float(cost) if isinstance(cost, int | float) else None,
                described=described_price(str(entry.get("description") or "")),
                litellm=None if local else lookup(model),
            )
        )
    return rows


def _cost_text(value: float) -> str:
    # One decimal for a cloud model (3.0), a whole 5 for a local one.
    return "5" if value == LOCAL_COST else f"{value:.1f}"


_COST_IN_RATINGS = re.compile(r"(ratings:\s*\{[^}\n]*\bcost:\s*)([0-9]+(?:\.[0-9]+)?)")
_ENTRY_START = re.compile(r"^  - name:\s*([^\s#]+)")


def fix_costs(text: str, rows: list[ModelPrices]) -> tuple[str, list[str], list[str]]:
    """`text` with each wrong `cost` set to what its price gives, editing
    only that number so comments and layout stay. Returns the new text, the
    names fixed, and the names that need a hand edit (no `cost` in a
    one-line `ratings: {...}`)."""
    wanted = {
        r.name: r.expected_cost
        for r in rows
        if r.expected_cost is not None and r.cost != r.expected_cost
    }
    lines = text.splitlines(keepends=True)
    fixed: list[str] = []
    current = None
    for i, line in enumerate(lines):
        start = _ENTRY_START.match(line)
        if start:
            current = start.group(1).strip("'\"")
            continue
        if current in wanted and line.startswith("    "):
            new, count = _COST_IN_RATINGS.subn(
                lambda m, v=wanted[current]: m.group(1) + _cost_text(v),
                line,
            )
            if count:
                lines[i] = new
                fixed.append(current)
                current = None
    by_hand = [name for name in wanted if name not in fixed]
    return "".join(lines), fixed, by_hand
