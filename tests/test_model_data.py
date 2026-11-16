"""model_data.py: the model data file. No network: the source rows are
written here in the shape LMArena, Epoch AI and LiteLLM publish them."""

from __future__ import annotations

from importlib.resources import files

import pytest
import yaml

from certo.model_data import build, dumps, model_key, parse
from certo.ratings import rate


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("anthropic/claude-opus-5-5", "claudeopus55"),
        ("openrouter/anthropic/claude-opus-5-5", "claudeopus55"),
        ("Claude Opus 5.5 (Max)", "claudeopus55"),
        ("ollama/gemma4:31b", "gemma431b"),
        ("Gemma 4 31B", "gemma431b"),
        ("ollama/gemma4:31b-it-qat", "gemma431b"),
        ("anthropic/claude-haiku-4-5-20251001", "claudehaiku45"),
        ("gemini/gemini-3.1-pro-preview", "gemini31pro"),
        ("Qwen3.8-27B", "qwen3827b"),
    ],
)
def test_a_model_key_takes_the_spelling_out_of_a_name(name, key):
    assert model_key(name) == key


def _row(name, rating, category="overall", **extra):
    return {"model_name": name, "rating": rating, "category": category, **extra}


def _data():
    lmarena = {
        "webdev": [_row("Claude Opus 5.5 (High)", 1790.0), _row("Claude Opus 5.5 (Max)", 1815.6)],
        "text_factuality": [_row("Claude Opus 5.5 (Max)", 1505.0)],
        "text": [
            _row("Claude Opus 5.5 (Max)", 1530.0, "creative_writing"),
            _row("Claude Opus 5.5 (Max)", 1514.0),  # overall: not a score Certo reads
            _row("Qwen3-8B", 1300.0, "creative_writing"),
        ],
        "agent": [
            _row("Claude Opus 5.5 (Max)", None, cost_per_task_p50=3.0, session_count=10),
            _row("Claude Opus 5.5 (High)", None, cost_per_task_p50=2.1, session_count=900),
        ],
    }
    eci = [{"Model": "Claude Opus 5.5", "eci": "168.5"}, {"Model": "Qwen3 8B", "eci": "130"}]
    prices = {
        "openrouter/anthropic/claude-opus-5-5": {
            "mode": "chat",
            "input_cost_per_token": 5e-6,
            "output_cost_per_token": 25e-6,
        },
        "claude-opus-5-5": {
            "mode": "chat",
            "input_cost_per_token": 4e-6,
            "output_cost_per_token": 20e-6,
        },
        "text-embedding-qwen3-8b": {"mode": "embedding", "input_cost_per_token": 1e-8},
        "sample_spec": {"mode": "chat"},
    }
    return build(lmarena, eci, prices, {"qwen3": "qwen38b"}, "2026-11-16")


def test_the_file_keeps_each_models_best_variant_and_the_most_used_variants_cost():
    data = _data()
    opus = data["models"]["claudeopus55"]
    assert opus["scores"] == {
        "epoch_eci": 168.5,
        "lmarena_creative_writing": 1530.0,
        "lmarena_text_factuality": 1505.0,
        "lmarena_webdev": 1815.6,
    }
    assert opus["cost_per_task"] == 2.1  # the (High) variant: 900 sessions
    # The provider's own id, not a reseller's.
    assert (opus["litellm"], opus["price_in"], opus["price_out"]) == ("claude-opus-5-5", 4.0, 20.0)
    assert data["models"]["qwen38b"]["litellm"] is None  # an embedding has no chat price
    assert [s["license"] for s in data["sources"]] == ["CC-BY-4.0", "CC-BY-4.0", "MIT"]


def test_read_back_any_id_for_a_model_finds_it_and_rates_it():
    file = parse(dumps(_data()))
    found = file.lookup("openrouter/anthropic/claude-opus-5-5")
    assert found is not None and found.cost_per_task == 2.1
    assert rate(found, file.anchors).ratings["code"] == 5.0
    qwen = file.lookup("ollama/qwen3", local=True)  # through the alias
    assert qwen is not None and qwen.local and qwen.scores["epoch_eci"] == 130.0
    assert file.lookup("ollama/flint:40b") is None


def test_an_unknown_format_is_refused():
    with pytest.raises(ValueError, match="format"):
        parse('{"format": 99}')


def test_the_shipped_file_reads_and_rates_certos_own_models():
    data = files("certo").joinpath("data")
    shipped = parse(data.joinpath("model_data.json").read_text(encoding="utf-8"))
    certos = yaml.safe_load(data.joinpath("models_list.yaml").read_text(encoding="utf-8"))
    without = sorted(m["name"] for m in certos["models"] if shipped.lookup(m["model"]) is None)
    # The local models no source rates: marked "no data", hand ratings kept.
    assert without == ["devstral-small-2-local", "flint-40b-local", "qwen3-coder-local"]
