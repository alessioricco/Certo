"""ratings.py: 1-5 ratings computed from third-party scores. No network:
the scores are written here, from LMArena's and Epoch AI's data of
2026-11-16."""

from __future__ import annotations

import pytest

from certo.ratings import (
    DEFAULT_ANCHORS,
    Anchor,
    ModelData,
    rate,
    task_cost_rating,
)


def test_an_anchor_draws_a_straight_line_between_its_points_capped_at_1_and_5():
    code = Anchor("lmarena_webdev", (1350, 1450, 1550, 1650, 1750))
    assert code.rating(1350) == 1.0 and code.rating(1750) == 5.0
    assert code.rating(1500) == 2.5
    assert code.rating(1000) == 1.0 and code.rating(1900) == 5.0
    uneven = Anchor("epoch_eci", (135, 145, 155, 162, 168))
    assert uneven.rating(165) == pytest.approx(4.5)


@pytest.mark.parametrize(
    ("dollars", "rating"),
    [(1.0, 3.0), (2.12, 2.5), (0.08, 4.8), (7.83, 1.5), (0.01, 4.9), (500, 1.0)],
)
def test_cost_per_agent_task_takes_half_a_point_per_doubling(dollars, rating):
    assert task_cost_rating(dollars) == rating


def test_a_cloud_model_is_rated_on_every_axis_from_its_sources():
    opus = ModelData(
        scores={
            "lmarena_webdev": 1816,
            "epoch_eci": 169,
            "lmarena_text_factuality": 1505,
            "lmarena_creative_writing": 1532,
        },
        cost_per_task=2.12,
        price_in=5,
        price_out=25,
    )
    rated = rate(opus, DEFAULT_ANCHORS)
    assert rated.ratings == {
        "code": 5.0,
        "reasoning": 5.0,
        "precision": 4.8,
        "writing": 4.6,
        "cost": 2.5,  # from the cost per task, not the list price
        "speed": 4.0,
    }
    assert rated.sources["cost"] == "cost per agent task"
    assert rated.missing == () and not rated.no_data


def test_without_a_cost_per_task_the_list_price_rates_the_cost():
    rated = rate(ModelData(price_in=1.0, price_out=5.0), DEFAULT_ANCHORS)
    assert rated.ratings["cost"] == 3.5 and rated.sources["cost"] == "list price"
    assert rate(ModelData(), DEFAULT_ANCHORS).missing[-1] == "cost"


def test_a_local_model_loses_a_point_on_capability_and_is_free_and_slow():
    qwen = ModelData(scores={"lmarena_webdev": 1590, "epoch_eci": 153}, local=True)
    rated = rate(qwen, DEFAULT_ANCHORS)
    assert rated.ratings == {"code": 2.4, "reasoning": 1.8, "cost": 5.0, "speed": 2.0}
    assert rated.sources["code"] == "lmarena_webdev, local −1"
    assert rated.missing == ("precision", "writing")
    low = rate(ModelData(scores={"lmarena_webdev": 1300}, local=True), DEFAULT_ANCHORS)
    assert low.ratings["code"] == 1.0  # never below 1


def test_a_model_no_source_rates_has_no_data():
    rated = rate(ModelData(local=True), DEFAULT_ANCHORS)
    assert rated.no_data
    assert rated.ratings == {"cost": 5.0, "speed": 2.0}


def test_own_results_shrink_in_and_move_a_rating_at_most_one_point():
    haiku = ModelData(scores={"lmarena_webdev": 1593}, cost_per_task=0.08)
    computed = rate(haiku, DEFAULT_ANCHORS).ratings["code"]
    assert computed == 3.4
    # 13 verified runs pointing at 5: 3.43 + 1.57 * 13/18 = 4.6, capped at +1.
    rated = rate(haiku, DEFAULT_ANCHORS, own={"code": (5.0, 13)})
    assert rated.ratings["code"] == 4.4
    assert rated.sources["code"] == "lmarena_webdev, own results (13 runs)"
    # Two runs move it little: 3.43 + 1.57 * 2/7.
    assert rate(haiku, DEFAULT_ANCHORS, own={"code": (5.0, 2)}).ratings["code"] == 3.9
    # Own results for an axis with no computed rating are ignored.
    assert "precision" not in rate(haiku, DEFAULT_ANCHORS, own={"precision": (4.0, 9)}).ratings
