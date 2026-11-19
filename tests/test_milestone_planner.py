"""milestone_planner.py: `--make-milestones`'s plan. No LLM: the model's
answer is given by a fake `complete`."""

from __future__ import annotations

from dataclasses import replace

import pytest
from model_file_helpers import model_file_config

from certo import milestone_planner
from certo.config import Config, ConfigError
from certo.milestone_planner import (
    choose_planner,
    milestone_sections,
    plan_milestones,
    save_plan,
)
from certo.milestones import parse_milestones

_TASK = "# Ledger\n\nA Python CLI that records expenses, with pytest tests.\n"
_PLAN = """## Milestone 1: Record expenses
Add `ledger.py` with `add(amount, note)` and tests.

## Milestone 2: Totals by month
Add `total(month)`. Done when its tests pass.
"""


def _cfg(**overrides) -> Config:
    base = Config(
        model="anthropic/claude-haiku-5-5",
        api_key="k",
        base_url=None,
        workspace=".",
        max_iterations=50,
        confirm_mode="never",
        execution="local",
    )
    return replace(base, **overrides)


def _answer(text: str, cost: float = 0.002):
    seen = {}

    def complete(cfg, prompt):
        seen["cfg"], seen["prompt"] = cfg, prompt
        return text, cost

    return complete, seen


def test_a_plan_is_the_task_as_written_then_the_milestones():
    complete, seen = _answer(_PLAN)
    planned = plan_milestones(_TASK, _cfg(), complete)

    assert planned.text == _TASK.rstrip() + "\n\n" + _PLAN.strip() + "\n"
    assert planned.titles == ("Record expenses", "Totals by month")
    assert (planned.model, planned.cost) == ("anthropic/claude-haiku-5-5", 0.002)
    # The task is in the prompt, and the plan reads as milestones with the
    # task as every milestone's context.
    assert "A Python CLI that records expenses" in seen["prompt"]
    plan = parse_milestones(planned.text)
    assert "A Python CLI that records expenses" in plan.context


def test_a_fenced_answer_with_a_preface_and_acceptance_blocks_is_cleaned():
    answer = (
        "Here is the plan:\n```markdown\n## Milestone 1: One\nDo one.\n"
        '```acceptance\n[{"kind": "file_exists", "path": "x"}]\n```\n'
        "## Milestone 2: Two\nDo two.\n```"
    )
    sections = milestone_sections(answer)
    assert sections is not None
    assert sections.startswith("## Milestone 1: One")
    assert "acceptance" not in sections and "Here is" not in sections
    planned = plan_milestones(_TASK, _cfg(), _answer(answer)[0])
    assert planned.titles == ("One", "Two")
    assert all(not m.acceptance for m in parse_milestones(planned.text).milestones)


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("ONE MILESTONE", "kept it as one milestone"),
        ("## Milestone 1: All\nBuild it all.", "wrote one milestone"),
        ("I would build it step by step.", "no milestone headings"),
        ("## Milestone 2: B\nb\n## Milestone 1: A\na", "couldn't be read"),
        (
            "\n".join(f"## Milestone {n}: M{n}\nDo {n}." for n in range(1, 10)),
            "9 milestones, more than 8",
        ),
    ],
)
def test_a_plan_that_cant_be_used_leaves_the_task_as_one(answer, reason):
    planned = plan_milestones(_TASK, _cfg(), _answer(answer)[0])
    assert planned.text is None
    assert reason in planned.reason


def test_a_failing_model_never_stops_the_run():
    def complete(cfg, prompt):
        raise TimeoutError("no answer in 600s")

    planned = plan_milestones(_TASK, _cfg(), complete)
    assert planned.text is None
    assert "failed: TimeoutError: no answer in 600s" in planned.reason


def test_the_plan_is_saved_in_the_projects_certo_folder(tmp_path):
    path = save_plan(str(tmp_path / "ledger"), "plan text\n")
    assert path == str(tmp_path / "ledger" / ".certo" / "milestones.md")
    assert open(path).read() == "plan text\n"
    assert (tmp_path / "ledger" / ".certo" / ".gitignore").exists()


_CATALOG = """
models:
  - name: cheap
    model: openai/cheap
    api_key: k
    ratings: {reasoning: 2, code: 4, cost: 5}
  - name: thinker
    model: anthropic/thinker
    api_key: k2
    ratings: {reasoning: 5, code: 4, cost: 3}
  - name: spare
    model: openai/spare
    api_key: k3
    activated: false
    ratings: {reasoning: 5, cost: 5}
task_profiles:
  planning:
    needs: {reasoning: 4}
  default:
    needs: {code: 3}
"""


def _files(tmp_path, catalog=_CATALOG) -> dict:
    return model_file_config(tmp_path, catalog)


def test_with_one_model_the_run_plans_with_its_own_model(tmp_path):
    cfg = _cfg(**_files(tmp_path))
    assert choose_planner(cfg) == (cfg, "the run's model")


def test_auto_model_plans_with_the_planning_profiles_first_model(tmp_path):
    cfg = _cfg(model_selection="auto", **_files(tmp_path))
    planner, how = choose_planner(cfg)
    assert (planner.model, how) == ("anthropic/thinker", "the 'planning' task profile")


def test_without_a_planning_profile_the_runs_model_plans(tmp_path):
    catalog = _CATALOG.replace("  planning:\n    needs: {reasoning: 4}\n", "")
    cfg = _cfg(model_selection="escalate", **_files(tmp_path, catalog))
    planner, how = choose_planner(cfg)
    assert planner is cfg and "no 'planning' task profile" in how


def test_the_planner_setting_names_a_model_in_models_yaml(tmp_path):
    cfg = _cfg(planner_model="cheap", **_files(tmp_path))
    planner, how = choose_planner(cfg)
    assert (planner.model, planner.api_key, how) == ("openai/cheap", "k", "CERTO_PLANNER_MODEL")


@pytest.mark.parametrize("name", ["spare", "nowhere"])
def test_a_planner_model_not_enabled_is_refused(tmp_path, name):
    cfg = _cfg(planner_model=name, **_files(tmp_path))
    with pytest.raises(ConfigError, match="isn't a model enabled in models.yaml"):
        choose_planner(cfg)


_BROKEN_LADDER = "escalation:\n  ladders:\n    hard:\n      - model: nowhere\n"


def test_a_broken_ladder_does_not_stop_the_planner_setting(tmp_path):
    cfg = _cfg(planner_model="cheap", **_files(tmp_path, _CATALOG + _BROKEN_LADDER))
    assert choose_planner(cfg)[0].model == "openai/cheap"


def test_a_broken_ladder_does_not_stop_the_planning_profile(tmp_path):
    cfg = _cfg(model_selection="escalate", **_files(tmp_path, _CATALOG + _BROKEN_LADDER))
    planner, how = choose_planner(cfg)
    assert (planner.model, how) == ("anthropic/thinker", "the 'planning' task profile")


def test_an_unreachable_local_planner_is_passed_over(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "certo.model_reachability.unreachable_reason",
        lambda entry, *a, **k: "down" if entry.name == "thinker" else None,
    )
    catalog = _CATALOG.replace("{reasoning: 2, code: 4, cost: 5}", "{reasoning: 4, cost: 1}")
    cfg = _cfg(model_selection="auto", **_files(tmp_path, catalog))
    planner, _how = choose_planner(cfg)
    assert planner.model == "openai/cheap"


def test_the_prompt_asks_for_milestone_headings_and_nothing_else():
    prompt = milestone_planner.PROMPT
    assert "## Milestone N: short title" in prompt
    assert "ONE MILESTONE" not in prompt  # filled in at call time
    assert "{size}" in prompt and "{task}" in prompt
    assert "{one}" in milestone_planner.SIZE_FREE


def _plan_of(n: int) -> str:
    return "\n".join(f"## Milestone {k}: Part {k}\nBuild part {k}.\n" for k in range(1, n + 1))


def test_a_count_asks_for_exactly_that_many_and_no_one_go():
    complete, seen = _answer(_plan_of(12))
    planned = plan_milestones(_TASK, _cfg(), complete, count=12)

    assert "Exactly 12 milestones" in seen["prompt"]
    assert "ONE MILESTONE" not in seen["prompt"]
    # More than the usual 8: the user asked for it.
    assert len(planned.titles) == 12 and planned.note == ""


def test_without_a_count_the_planner_chooses():
    complete, seen = _answer(_PLAN)
    plan_milestones(_TASK, _cfg(), complete)
    assert "Between 2 and 8 milestones" in seen["prompt"] and "ONE MILESTONE" in seen["prompt"]


def test_a_wrong_count_is_asked_again_once():
    answers = [_plan_of(3), _plan_of(4)]
    prompts = []

    def complete(cfg, prompt):
        prompts.append(prompt)
        return answers.pop(0), 0.001

    planned = plan_milestones(_TASK, _cfg(), complete, count=4)

    assert len(prompts) == 2
    assert "Your previous plan had 3 milestones" in prompts[1] and "exactly 4" in prompts[1]
    assert len(planned.titles) == 4 and planned.note == ""
    assert planned.cost == pytest.approx(0.002)


def test_a_count_still_wrong_runs_as_written_with_a_note():
    complete, _ = _answer(_plan_of(5))
    planned = plan_milestones(_TASK, _cfg(), complete, count=4)

    assert len(planned.titles) == 5
    assert planned.note == ("you asked for 4 milestones; the planner wrote 5, which run as written")


def test_a_retry_that_cant_be_read_keeps_the_first_plan():
    answers = [_plan_of(3), "Sorry, I can't."]
    planned = plan_milestones(_TASK, _cfg(), lambda c, p: (answers.pop(0), 0.0), count=4)
    assert len(planned.titles) == 3 and "you asked for 4" in planned.note
