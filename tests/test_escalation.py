"""escalation.py: explicit and derived ladders, with fake models (no SDK)."""

from __future__ import annotations

import pytest
from model_file_helpers import write_split_model_files

from certo.escalation import (
    FileChanges,
    RungResult,
    climb_line,
    handoff_task,
    failure_reason,
    EscalationError,
    derive_ladder,
    describe_ladder,
    ladder_from_models,
    resolve_ladder,
    spread_indices,
)
from certo.model_catalog import load_model_catalog

_CATALOG = """
models:
  - name: tiny
    model: ollama/tiny
    base_url: http://localhost:11434
    ratings: {reasoning: 1, code: 1, cost: 5}
  - name: local
    model: ollama/qwen
    base_url: http://localhost:11434
    ratings: {reasoning: 2, code: 3, cost: 5}
  - name: mid
    model: openai/luna
    api_key: k
    ratings: {reasoning: 3, code: 4, cost: 4}
  - name: twin
    model: openai/twin
    api_key: k
    ratings: {reasoning: 4, code: 3, cost: 3}
  - name: strong
    model: anthropic/sonnet
    api_key: k
    ratings: {reasoning: 5, code: 5, cost: 2}
  - name: parked
    model: openai/old
    api_key: k
    ratings: {reasoning: 9, code: 9, cost: 9}
    activated: false
task_profiles:
  coding:
    triggers: [implement]
    weights: {code: 3, reasoning: 0, cost: 1}
  thinking:
    triggers: [design]
    weights: {reasoning: 3, code: 0, cost: 1}
  default:
    weights: {reasoning: 1, code: 1, cost: 1}
"""


def _catalog(tmp_path, extra: str = "", text: str = _CATALOG):
    return load_model_catalog(**write_split_model_files(tmp_path, text + extra))


def _names(ladder):
    return [r.name for r in ladder.rungs]


@pytest.mark.parametrize(
    ("n", "k", "expected"),
    [
        (2, 3, [0, 1]),
        (3, 3, [0, 1, 2]),
        (5, 3, [0, 2, 4]),
        (4, 3, [0, 2, 3]),
        (10, 4, [0, 3, 6, 9]),
    ],
)
def test_spread_keeps_the_first_and_last_and_spreads_the_rest(n, k, expected):
    assert spread_indices(n, k) == expected


def test_derived_ladder_keeps_the_best_of_the_cheapest(tmp_path):
    ladder = derive_ladder(_catalog(tmp_path, "escalation: {max_rungs: 5}\n"))

    assert ladder.kind == "derived"
    # capability (reasoning + code, cost left out): tiny 2, local 5, mid 7, twin 7, strong 10.
    # tiny costs the same as local and is weaker; twin costs more than mid and
    # is no better. Neither is in the ladder.
    assert _names(ladder) == ["local", "mid", "strong"]
    assert [r.capability for r in ladder.rungs] == [5, 7, 10]
    assert ladder.skipped == (
        "tiny (local is at least as capable and costs no more)",
        "twin (mid is at least as capable and costs no more)",
    )


def test_derived_ladder_is_capped_by_max_rungs(tmp_path):
    # twin at 8: four models each beat every cheaper one (local 5, mid 7, twin 8, strong 10).
    text = _CATALOG.replace("{reasoning: 4, code: 3, cost: 3}", "{reasoning: 4, code: 4, cost: 3}")
    ladder = derive_ladder(_catalog(tmp_path, text=text))
    # 4 kept models, 3 rungs: the best of the cheapest, one between, the strongest.
    assert _names(ladder) == ["local", "twin", "strong"]


def test_ties_on_capability_and_cost_go_to_the_name(tmp_path):
    text = _CATALOG.replace("{reasoning: 4, code: 3, cost: 3}", "{reasoning: 3, code: 4, cost: 4}")
    ladder = derive_ladder(_catalog(tmp_path, "escalation: {max_rungs: 5}\n", text))
    assert _names(ladder) == ["local", "mid", "strong"]
    assert "twin (mid is at least as capable and costs no more)" in ladder.skipped


def test_a_model_without_a_cost_rating_counts_as_the_most_expensive(tmp_path):
    text = _CATALOG.replace("{reasoning: 4, code: 3, cost: 3}", "{reasoning: 4, code: 3}")
    ladder = derive_ladder(_catalog(tmp_path, "escalation: {max_rungs: 5}\n", text))
    assert _names(ladder) == ["local", "mid", "strong"]
    assert "twin (strong is at least as capable and costs no more)" in ladder.skipped


def test_inactive_models_are_never_in_a_derived_ladder(tmp_path):
    ladder = derive_ladder(_catalog(tmp_path, "escalation: {max_rungs: 9}\n"))
    assert "parked" not in _names(ladder)
    assert not any(s.startswith("parked") for s in ladder.skipped)


def test_task_profiles_dont_change_a_derived_ladder(tmp_path):
    """Capability is reasoning + code here (every axis but cost), whatever
    profile the task would match for --auto-model."""
    catalog = _catalog(tmp_path, "escalation: {max_rungs: 5}\n")
    ladder = derive_ladder(catalog)

    assert ladder.label == "derived ladder (from the ratings)"
    assert _names(ladder) == ["local", "mid", "strong"]
    assert [r.capability for r in ladder.rungs] == [5, 7, 10]


def test_capability_is_the_plain_sum_of_every_axis_but_cost():
    from certo.model_catalog import ModelCatalogEntry, capability

    entry = ModelCatalogEntry(
        name="m", model="x/m", ratings={"reasoning": 3, "precision": 2, "code": 4, "cost": 5}
    )
    assert capability(entry, "cost") == 9
    assert capability(entry, "precision") == 12  # a different cost axis is left out instead


def test_the_cost_axis_is_configurable(tmp_path):
    text = _CATALOG.replace("cost:", "price:")
    ladder = derive_ladder(
        _catalog(tmp_path, "escalation: {cost_axis: price, max_rungs: 5}\n", text)
    )
    assert ladder.cost_axis == "price"
    assert _names(ladder) == ["local", "mid", "strong"]
    assert [r.capability for r in ladder.rungs] == [5, 7, 10]
    assert ladder.rungs[0].cost_rating == 5


def test_a_cost_rating_under_another_name_counts_as_capability_without_cost_axis(tmp_path):
    text = _CATALOG.replace("cost:", "price:")
    ladder = derive_ladder(_catalog(tmp_path, "escalation: {max_rungs: 5}\n", text))
    # 'price' is an ordinary axis unless escalation.cost_axis names it. With
    # no cost rating anywhere there is no price to compare: least capable
    # first, nothing left out.
    assert ladder.rungs[0].cost_rating is None
    assert ladder.rungs[0].name == "tiny"
    assert ladder.rungs[0].capability == 7  # reasoning 1 + code 1 + price 5
    assert _names(ladder) == ["tiny", "local", "twin", "mid", "strong"]
    assert ladder.skipped == ()


_LADDERS = """escalation:
  ladders:
    default:
      - model: local
        retries: 1
      - model: parked
      - model: strong
        reasoning_effort: max
    cloud:
      - model: mid
      - model: strong
"""


def test_an_explicit_default_ladder_wins_over_derivation(tmp_path):
    ladder = resolve_ladder(_catalog(tmp_path, _LADDERS), None)

    assert ladder.kind == "explicit"
    assert ladder.name == "default"
    assert _names(ladder) == ["local", "strong"]
    assert ladder.source == "escalation.yaml"
    assert ladder.rungs[0].retries == 1
    assert ladder.rungs[1].reasoning_effort == "max"
    assert ladder.skipped == ("parked (activated: false)",)


def test_a_named_ladder(tmp_path):
    assert _names(resolve_ladder(_catalog(tmp_path, _LADDERS), "cloud")) == ["mid", "strong"]


def test_no_default_ladder_means_derived(tmp_path):
    text = _LADDERS.replace("    default:", "    other:")
    assert resolve_ladder(_catalog(tmp_path, text), None).kind == "derived"


def test_an_unknown_ladder_lists_the_ones_found(tmp_path):
    with pytest.raises(EscalationError, match="no escalation ladder named 'fast'.*cloud, default"):
        resolve_ladder(_catalog(tmp_path, _LADDERS), "fast")


def test_an_unknown_ladder_without_any_ladders(tmp_path):
    with pytest.raises(EscalationError, match="only a derived ladder is available"):
        resolve_ladder(_catalog(tmp_path), "fast")


def test_a_ladder_from_model_names(tmp_path):
    ladder = ladder_from_models(_catalog(tmp_path), ["local", "parked", "strong"])
    assert _names(ladder) == ["local", "strong"]
    assert ladder.source == "the benchmark arm's models"


def test_which_verdicts_escalate(tmp_path):
    ladder = resolve_ladder(_catalog(tmp_path, _LADDERS), "cloud")
    for verdict in (
        "retry_exhausted",
        "no_progress",
        "timed_out",
        "incomplete",
        "stuck",
        "inconclusive",
    ):
        assert ladder.escalates_on(verdict), verdict
    for verdict in (
        "verified",
        "budget_exhausted",
        "confirmation_required",
        "acceptance_failed",
    ):
        assert not ladder.escalates_on(verdict), verdict


def test_acceptance_failed_escalates_only_when_the_ladder_opts_in(tmp_path):
    text = (
        _LADDERS
        + "    careful:\n      escalate_on_acceptance_failed: true\n      rungs:\n        - model: local\n        - model: strong\n"
    )
    ladder = resolve_ladder(_catalog(tmp_path, text), "careful")
    assert ladder.escalates_on("acceptance_failed")


def test_describe_a_derived_ladder(tmp_path):
    lines = describe_ladder(derive_ladder(_catalog(tmp_path)))
    assert lines == [
        "Escalation: derived ladder (from the ratings), 3 rung(s):",
        "  1. local (capability 5, cost rating 5; effort default)",
        "  2. mid (capability 7, cost rating 4; effort default)",
        "  3. strong (capability 10, cost rating 2; effort default)",
        (
            "  Skipped: tiny (local is at least as capable and costs no more), "
            "twin (mid is at least as capable and costs no more)"
        ),
    ]


def test_describe_an_explicit_ladder(tmp_path):
    lines = describe_ladder(resolve_ladder(_catalog(tmp_path, _LADDERS), None))
    assert lines == [
        "Escalation: explicit ladder 'default', 2 rung(s):",
        "  1. local (1 fix attempt(s); effort default)",
        "  2. strong (effort max)",
        "  Skipped: parked (activated: false)",
    ]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("LLMAuthenticationError: invalid x-api-key", "the provider rejected its API key"),
        ("LLMTimeoutError: took too long", "the provider didn't answer in time"),
        ("LLMServiceUnavailableError: down", "the provider couldn't be reached"),
    ],
)
def test_a_known_provider_failure_has_a_plain_reason(failure, expected):
    name = failure.split(":")[0]
    assert failure_reason(failure) == f"{expected} ({name})"


def test_an_unknown_failure_has_no_plain_reason():
    assert failure_reason("RuntimeError: boom") is None
    assert failure_reason(None) is None


def test_handoff_task_finds_the_task_only_in_a_handoff():
    assert handoff_task("Note.\n\nThe task:\n\n# Title\n\nBody") == "# Title\n\nBody"
    assert handoff_task("# Title\n\nThe task: is in this sentence") is None


def _rung(verdict, created=()):
    return RungResult(1, "m", "x/m", verdict, 0, 1.0, None, changes=FileChanges(created=created))


def test_which_rungs_wrote_code():
    assert _rung("verified").wrote_code
    assert _rung(None, created=("a.py",)).wrote_code  # failed after writing a file
    assert not _rung(None).wrote_code  # stopped at a provider error first
    assert not _rung("unchanged").wrote_code
    assert not _rung("inconclusive").wrote_code


_TWO_EFFORTS = """escalation:
  ladders:
    default:
      - model: local
        reasoning_effort: low
      - model: local
        reasoning_effort: high
"""


def test_one_model_at_two_efforts_is_told_apart_by_its_effort(tmp_path):
    ladder = resolve_ladder(_catalog(tmp_path, _TWO_EFFORTS), None)
    first = RungResult(1, "local", "ollama/q", "no_progress", 1, 1.0, None, reasoning_effort="low")

    assert [r.label for r in ladder.rungs] == ["local (effort low)", "local (effort high)"]
    assert climb_line(first, ladder.rungs[1], 2, 2) == (
        "Certo: local (effort low) ended no_progress after 1 fix attempt; "
        "escalating to local (effort high) (rung 2 of 2)."
    )
    assert first.described == "local (ollama/q, effort low)"
    assert first.to_dict()["reasoning_effort"] == "low"
    # A rung without its own effort runs at its model entry's, if any.
    assert _rung("verified").described == "m (x/m, effort default)"


def test_to_dict_carries_the_rungs_own_tool_call_reminders():
    rung = RungResult(1, "m", "x/m", "verified", 0, 1.0, None, tool_call_reminders=2)

    assert rung.to_dict()["tool_call_reminders"] == 2
    assert _rung("verified").to_dict()["tool_call_reminders"] == 0


def test_a_restarted_handoff_says_the_changes_were_undone():
    from certo.escalation import handoff_message

    message = handoff_message(
        "Build it",
        [_rung("retry_exhausted", created=("app.py",))],
        "E  assert 1 == 2",
        restarted=True,
    )

    assert "Certo has undone its changes" in message
    assert "- Files it created: app.py" in message
    assert "failing, on its version (now undone):" in message


def test_a_restart_after_no_work_reads_like_a_continue():
    from certo.escalation import handoff_message

    message = handoff_message("Build it", [_rung("inconclusive")], "", restarted=True)

    assert "undone" not in message
