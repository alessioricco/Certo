"""Rough model prices, for a cost estimate before anything runs: the
benchmark plan and the escalation prompt. From LiteLLM's price list; a
local model costs nothing."""

from __future__ import annotations

import ipaddress
import math
import re
from urllib.parse import urlparse

from .model_catalog import ModelCatalogEntry

# A rough per-run token count for the cost estimate, before any run has
# happened. One sample task run in the README used ~800k tokens, most of
# them cached input; this errs on the expensive side.
ESTIMATE_INPUT_TOKENS = 500_000
ESTIMATE_OUTPUT_TOKENS = 20_000
_LOCAL_PREFIXES = ("ollama", "ollama_chat", "lm_studio", "hosted_vllm", "llamafile")


def is_local_model_id(model: str) -> bool:
    """A model id whose provider prefix is a local server (Ollama and
    friends). Without the entry's address this is all that is known."""
    return model.split("/", 1)[0] in _LOCAL_PREFIXES


def is_local(entry: ModelCatalogEntry) -> bool:
    """A model served on this machine or this network (Ollama and friends)."""
    return is_local_model(entry.model, entry.base_url)


def is_local_model(model: str, base_url: str | None) -> bool:
    """`is_local` for a model id and its server address."""
    if is_local_model_id(model):
        return True
    host = urlparse(base_url or "").hostname
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_unspecified


def estimate_run_cost(entry: ModelCatalogEntry) -> float | None:
    """A rough cost of one run in USD, from LiteLLM's prices, or None when
    the model has no known price."""
    return 0.0 if is_local(entry) else guess_run_cost(entry.model)


def guess_run_cost(model: str) -> float | None:
    """The fixed guess for one run of a cloud model: ESTIMATE_INPUT_TOKENS
    and ESTIMATE_OUTPUT_TOKENS at LiteLLM's list price, or None when the
    model has no known price. run_stats.estimate_for prefers measured runs."""
    try:
        import litellm

        prompt, completion = litellm.cost_per_token(
            model=model,
            prompt_tokens=ESTIMATE_INPUT_TOKENS,
            completion_tokens=ESTIMATE_OUTPUT_TOKENS,
        )
    except Exception:  # noqa: BLE001 - unknown model or pricing: no estimate
        return None
    total = prompt + completion
    return total if total > 0 else None


# --- the `cost` rating from a price (models_list.yaml.example's rubric) --------

# The price a catalog entry is rated at: the first "$X in / $Y out" of its
# description (per 1M tokens).
_DESCRIBED_PRICE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?) in\s*/\s*\$([0-9]+(?:\.[0-9]+)?) out")


def described_price(description: str) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens from a catalog description, or None."""
    found = _DESCRIBED_PRICE.search(" ".join(description.split()))
    return (float(found.group(1)), float(found.group(2))) if found else None


def cost_rating(price_in: float, price_out: float) -> float:
    """The `cost` rating of a cloud model: from the blended price p per 1M
    tokens (3 input to 1 output), 4 - log2(p) / 2, one decimal, kept between
    1 and 4.9 (5 is for local models). Each doubling of the price takes
    half a point."""
    blended = (3 * price_in + price_out) / 4
    if blended <= 0:
        return 4.9
    return round(min(4.9, max(1.0, 4 - math.log2(blended) / 2)), 1)


def litellm_price(model: str) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens from the price list of the
    installed LiteLLM (no network), or None when it doesn't know the id."""
    try:
        import litellm
    except ImportError:
        return None
    for key in (model, model.split("/", 1)[-1]):
        info = litellm.model_cost.get(key)
        if info and info.get("input_cost_per_token") is not None:
            per_in = float(info.get("input_cost_per_token") or 0) * 1_000_000
            per_out = float(info.get("output_cost_per_token") or 0) * 1_000_000
            return round(per_in, 4), round(per_out, 4)
    return None
