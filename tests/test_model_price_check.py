"""`certo models check`: prices and cost ratings against a price list. The
LiteLLM lookup is faked, so no test depends on the installed price list."""

from __future__ import annotations

import argparse

import yaml
from test_init_cmd import Script

from certo.model_price_check import fix_costs, read_prices
from certo.model_pricing import cost_rating, described_price
from certo.models_cmd import check_main

_LIST = """\
models:
  # a comment that must stay
  - name: cheap
    model: openai/cheap-1
    description: >
      $0.10 in / $0.50 out per 1M.
    ratings: {reasoning: 3, precision: 3, code: 3, cost: 4.9}

  - name: mid
    model: anthropic/mid-1
    description: >
      $2 in / $10 out per 1M.
    ratings: {reasoning: 4, precision: 4, code: 5, cost: 2}

  - name: moved
    model: gemini/moved-1
    description: >
      $4 in / $20 out per 1M from next month.
    ratings: {reasoning: 5, precision: 4, code: 5, cost: 2.5}

  - name: unknown
    model: moonshot/typo-1
    description: >
      No price written here.
    ratings: {reasoning: 3, precision: 3, code: 3, cost: 3}

  - name: local
    model: ollama/qwen3.8:27b
    ratings: {reasoning: 3, precision: 3, code: 2, cost: 5}
"""

_LITELLM = {
    "openai/cheap-1": (0.1, 0.5),
    "anthropic/mid-1": (2.0, 10.0),
    "gemini/moved-1": (2.0, 10.0),
}


def _lookup(model):
    return _LITELLM.get(model)


def _problems(text=_LIST):
    return {r.name: r.problems() for r in read_prices(text, _lookup)}


def test_cost_rating_halves_a_point_per_doubling():
    assert cost_rating(0.1, 0.5) == 4.9  # $0.20 blended, capped
    assert cost_rating(1, 1) == 4.0
    assert cost_rating(2, 10) == 3.0  # $4
    assert cost_rating(4, 20) == 2.5  # $8
    assert cost_rating(10, 50) == 1.8  # $20
    assert cost_rating(1000, 1000) == 1.0  # floor


def test_described_price_is_the_first_one_across_line_breaks():
    assert described_price("Mid tier: $4 in /\n $20 out per 1M ($2 / $10 until then)") == (4, 20)
    assert described_price("No price.") is None


def test_each_kind_of_problem_is_reported():
    problems = _problems()

    assert problems["cheap"] == []
    assert problems["mid"] == ["cost 2, its price gives 3"]
    assert problems["moved"] == ["price $4 / $20 in its description, $2 / $10 in LiteLLM's list"]
    assert problems["unknown"] == [
        "not in LiteLLM's price list: check the id",
        'no "$X in / $Y out" price in its description',
    ]
    assert problems["local"] == []


def test_a_local_model_is_always_5():
    text = _LIST.replace("code: 2, cost: 5}", "code: 2, cost: 4}")

    assert _problems(text)["local"] == ["cost 4, but a local model is free: 5"]


def test_fix_changes_only_the_wrong_numbers():
    rows = read_prices(_LIST, _lookup)

    new, fixed, by_hand = fix_costs(_LIST, rows)

    assert fixed == ["mid"] and by_hand == []
    assert "code: 5, cost: 3.0}" in new
    assert "# a comment that must stay" in new
    assert new.replace("cost: 3.0}", "cost: 2}", 1) == _LIST
    assert yaml.safe_load(new)["models"][1]["ratings"]["cost"] == 3.0


def test_a_block_style_ratings_map_is_left_for_a_hand_edit():
    text = _LIST.replace(
        "    ratings: {reasoning: 4, precision: 4, code: 5, cost: 2}",
        "    ratings:\n      reasoning: 4\n      cost: 2",
    )

    _new, fixed, by_hand = fix_costs(text, read_prices(text, _lookup))

    assert fixed == [] and by_hand == ["mid"]


def _check(tmp_path, *, fix=False, text=_LIST):
    path = tmp_path / "models_list.yaml"
    path.write_text(text)
    script = Script()
    args = argparse.Namespace(file=str(path), fix=fix)
    code = check_main(args, prompter=script.prompter(), lookup=_lookup)
    return code, script.text, path


def test_check_lists_what_needs_a_look_and_exits_1(tmp_path):
    code, text, path = _check(tmp_path)

    assert code == 1
    assert "5 models, against LiteLLM's price list." in text
    assert "  mid (anthropic/mid-1)\n    - cost 2, its price gives 3" in text
    assert "cheap (" not in text
    assert "certo models check --fix" in text
    assert path.read_text() == _LIST  # nothing written


def test_check_fix_writes_a_backup_and_leaves_the_price_questions(tmp_path):
    code, text, path = _check(tmp_path, fix=True)

    assert code == 1  # the price that differs and the unknown id remain
    assert "Fixed the cost of 1 model(s): mid." in text
    assert (tmp_path / "models_list.yaml.bak").read_text() == _LIST
    assert "cost: 3.0}" in path.read_text()


def test_check_passes_when_everything_agrees(tmp_path):
    clean = _LIST.split("  - name: moved")[0].replace("cost: 2}", "cost: 3.0}")

    code, text, _path = _check(tmp_path, text=clean)

    assert code == 0
    assert "Every price and cost rating agrees." in text


def test_check_fix_exits_0_when_it_fixed_everything(tmp_path):
    only_cost = _LIST.split("  - name: moved")[0]

    code, _text, _path = _check(tmp_path, fix=True, text=only_cost)

    assert code == 0


def test_the_shipped_example_has_only_known_ids():
    # Every cloud id of the example is one LiteLLM can price: an unknown id
    # usually means a typo or a retired model. Uses the installed LiteLLM.
    from pathlib import Path

    example = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "certo"
        / "examples"
        / "models_list.yaml.example"
    )
    rows = read_prices(example.read_text())
    unknown = [r.name for r in rows if not r.local and r.litellm is None]

    assert unknown == []
