"""Fit-based auto-model (model_catalog.rank_by_fit / rank_for_profile):
the least costly of the models that meet a task's needs, then climbing.
No model call."""

from __future__ import annotations

from certo.model_catalog import (
    ModelCatalog,
    ModelCatalogEntry,
    TaskProfile,
    _parse_task_profile,
    capability,
    fit_note,
    meets,
    rank_by_fit,
    rank_for_profile,
    shortfall,
)


def _m(name, **ratings) -> ModelCatalogEntry:
    return ModelCatalogEntry(name=name, model=f"x/{name}", ratings=ratings)


# The Author's models, with the ratings of their own list (2026-11-14).
_MODELS = [
    _m("qwen", reasoning=3, precision=3, code=2, writing=3, speed=1, cost=5),
    _m("haiku", reasoning=3, precision=3, code=4, writing=3, speed=5, cost=4),
    _m("luna", reasoning=3, precision=4, code=3, writing=4, speed=5, cost=4),
    _m("terra", reasoning=4, precision=4, code=4, writing=4, speed=4, cost=3),
    _m("sol", reasoning=4, precision=5, code=4, writing=5, speed=4, cost=2),
    _m("sonnet", reasoning=4, precision=4, code=5, writing=4, speed=4, cost=2),
    _m("opus", reasoning=5, precision=5, code=5, writing=5, speed=3, cost=2),
    _m("fable", reasoning=5, precision=5, code=5, writing=5, speed=3, cost=1),
]
_CATALOG = ModelCatalog(models=_MODELS, task_profiles=[])


def _order(**needs) -> list[str]:
    return [m.name for m in rank_by_fit(_CATALOG, needs)]


def test_each_model_wins_where_it_fits():
    assert _order(code=4)[0] == "haiku"  # a game feature
    assert _order(precision=4, code=3)[0] == "luna"  # exact output
    assert _order(reasoning=4, code=4)[0] == "terra"  # a hard bug
    assert _order(reasoning=5, precision=5)[0] == "opus"  # architecture
    assert _order(writing=3)[0] == "qwen"  # docs, slow is fine
    assert _order(code=3, speed=4)[0] == "haiku"  # needed now: no local model


def test_the_fallback_climbs_among_the_models_that_fit():
    assert _order(code=4) == ["haiku", "terra", "sol", "sonnet", "opus", "fable", "luna", "qwen"]


def test_neither_cost_nor_capability_alone_wins_everything():
    firsts = {_order(**n)[0] for n in ({"code": 4}, {"writing": 3}, {"reasoning": 5})}
    assert firsts == {"haiku", "qwen", "opus"}


def test_when_nothing_fits_the_closest_goes_first():
    # sonnet (reasoning 1 short, speed 1) and opus (speed 2) are 2 short each.
    assert _order(reasoning=5, code=5, speed=5)[:2] == ["sonnet", "opus"]
    assert shortfall(_MODELS[1], {"reasoning": 5, "code": 5, "speed": 5}) == 3


def test_an_unrated_axis_never_fits():
    entry = _m("old", code=5, cost=5)

    assert not meets(entry, {"writing": 1})


def test_speed_is_not_capability():
    assert capability(_m("a", code=3, speed=5, cost=1), "cost") == 3


def test_a_profile_with_needs_ignores_its_weights():
    profile = _parse_task_profile(
        "build", {"triggers": ["build"], "needs": {"code": 4}, "weights": {"cost": 9}}
    )

    ranked, how = rank_for_profile(_CATALOG, profile)

    assert ranked[0].name == "haiku"
    assert "least costly of the models that meet the needs (code 4+)" in how


def test_a_pinned_model_goes_first_and_the_fit_orders_the_rest():
    profile = TaskProfile(name="build", needs={"code": 4}, model="sonnet")

    ranked, how = rank_for_profile(_CATALOG, profile)

    assert [m.name for m in ranked[:3]] == ["sonnet", "haiku", "terra"]
    assert how == "the profile names sonnet; fallbacks by fit"


def test_fit_notes_say_why():
    profile = TaskProfile(name="build", needs={"code": 4})

    assert fit_note(_MODELS[1], profile) == "fits, cost 4"
    assert fit_note(_MODELS[0], profile) == "below: code 2 < 4, cost 5"
