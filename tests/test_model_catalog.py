"""Tests for model_catalog.py: pure parsing/classification/scoring, no SDK,
no network. Every YAML fixture is written to tmp_path and parsed for real —
no mocking of yaml.safe_load itself.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import yaml
from model_file_helpers import write_model_files, write_split_model_files

from certo.model_catalog import (
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogError,
    TaskProfile,
    classification_titles,
    classify_task,
    find_trigger,
    find_trigger_in,
    load_model_catalog,
    rank_candidates,
    rank_for_profile,
    score_entry,
    task_title,
)
from certo.milestones import milestone_task, parse_milestones

_MINIMAL_YAML = """
models:
  - name: only-one
    model: openai/gpt-4o-mini
    ratings: {reasoning: 2, cost: 5}
"""

_FULL_YAML = """
models:
  - name: fast-cheap
    model: openai/gpt-4o-mini
    api_key: sk-fake
    description: "Fast and cheap."
    ratings: {reasoning: 2, cost: 5, precision: 3, code: 3}
  - name: balanced
    model: anthropic/claude-sonnet-4-5-20250929
    ratings: {reasoning: 4, cost: 3, precision: 4, code: 4}
  - name: deep-reasoner
    model: anthropic/claude-opus-4
    base_url: "https://example.invalid"
    reasoning_effort: high
    ratings: {reasoning: 5, cost: 1, precision: 5, code: 5}

task_profiles:
  debugging:
    triggers: [fix, bug, crash]
    weights: {reasoning: 3, precision: 2, code: 1, cost: 0.5}
  scaffolding:
    triggers: [scaffold, "create a new"]
    weights: {cost: 2, code: 1}
  default:
    weights: {reasoning: 1, cost: 1, precision: 1, code: 1}
"""


def _write(tmp_path, text: str) -> tuple[str, str]:
    """Both model files, from one combined text (see conftest)."""
    return write_model_files(tmp_path, text)


def _catalog_files(tmp_path, text: str) -> dict:
    """`load_model_catalog` keywords for every file in `text`, task
    profiles and escalation in their own files."""
    return write_split_model_files(tmp_path, text)


def _list_only(tmp_path, list_text: str) -> tuple[str, str]:
    """A hand-written models_list.yaml (for malformed lists), with a
    minimal models.yaml."""
    (tmp_path / "models_list.yaml").write_text(list_text)
    (tmp_path / "models.yaml").write_text("models:\n  - name: foo\n")
    return str(tmp_path / "models_list.yaml"), str(tmp_path / "models.yaml")


# --- load_model_catalog: happy paths -----------------------------------


def test_loads_minimal_catalog_with_one_model_and_no_profiles(tmp_path):
    catalog = load_model_catalog(**_catalog_files(tmp_path, _MINIMAL_YAML))

    assert len(catalog.models) == 1
    assert catalog.models[0] == ModelCatalogEntry(
        name="only-one",
        model="openai/gpt-4o-mini",
        ratings={"reasoning": 2.0, "cost": 5.0},
    )
    assert catalog.task_profiles == []


def test_loads_full_catalog_with_profiles(tmp_path):
    catalog = load_model_catalog(**_catalog_files(tmp_path, _FULL_YAML))

    assert [m.name for m in catalog.models] == ["fast-cheap", "balanced", "deep-reasoner"]
    assert catalog.models[0].api_key == "sk-fake"
    assert catalog.models[2].base_url == "https://example.invalid"
    assert catalog.models[2].reasoning_effort == "high"
    assert {p.name for p in catalog.task_profiles} == {"debugging", "scaffolding", "default"}


# --- activated ---------------------------------------------------------


def test_activated_defaults_to_true_when_omitted(tmp_path):
    catalog = load_model_catalog(**_catalog_files(tmp_path, _MINIMAL_YAML))

    assert catalog.models[0].activated is True


def test_activated_false_is_parsed(tmp_path):
    path = _write(
        tmp_path,
        "models:\n  - name: foo\n    model: openai/gpt-4o\n    activated: false\n",
    )
    catalog = load_model_catalog(*path)

    assert catalog.models[0].activated is False


def test_activated_true_is_parsed(tmp_path):
    path = _write(
        tmp_path,
        "models:\n  - name: foo\n    model: openai/gpt-4o\n    activated: true\n",
    )
    catalog = load_model_catalog(*path)

    assert catalog.models[0].activated is True


def test_non_boolean_activated_raises(tmp_path):
    path = _write(
        tmp_path,
        "models:\n  - name: foo\n    model: openai/gpt-4o\n    activated: maybe\n",
    )
    with pytest.raises(ModelCatalogError, match="'activated'"):
        load_model_catalog(*path)


def test_duplicate_name_still_raises_when_one_is_deactivated(tmp_path):
    path = _write(
        tmp_path,
        "models:\n"
        "  - name: dup\n    model: openai/gpt-4o\n    activated: false\n"
        "  - name: dup\n    model: anthropic/claude-sonnet-4-5-20250929\n",
    )
    with pytest.raises(ModelCatalogError, match="duplicate model name"):
        load_model_catalog(*path)


# --- load_model_catalog: error paths -------------------------------------


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(ModelCatalogError, match="doesn't exist"):
        load_model_catalog(str(tmp_path / "missing.yaml"), str(tmp_path / "models.yaml"))


def test_invalid_yaml_raises(tmp_path):
    path = _list_only(tmp_path, "models: [this is not: valid: yaml: at all")
    with pytest.raises(ModelCatalogError, match="not valid YAML"):
        load_model_catalog(*path)


def test_non_mapping_top_level_raises(tmp_path):
    path = _list_only(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ModelCatalogError, match="mapping"):
        load_model_catalog(*path)


def test_missing_models_key_raises(tmp_path):
    path = _list_only(tmp_path, "description: no models\n")
    with pytest.raises(ModelCatalogError, match="non-empty 'models' list"):
        load_model_catalog(*path)


def test_empty_models_list_raises(tmp_path):
    path = _list_only(tmp_path, "models: []\n")
    with pytest.raises(ModelCatalogError, match="non-empty 'models' list"):
        load_model_catalog(*path)


def test_model_entry_missing_name_raises(tmp_path):
    path = _list_only(tmp_path, "models:\n  - model: openai/gpt-4o\n")
    with pytest.raises(ModelCatalogError, match="'name'"):
        load_model_catalog(*path)


def test_model_entry_missing_model_id_raises(tmp_path):
    path = _list_only(tmp_path, "models:\n  - name: foo\n")
    with pytest.raises(ModelCatalogError, match="'model'"):
        load_model_catalog(*path)


def test_duplicate_model_names_raise(tmp_path):
    path = _write(
        tmp_path,
        "models:\n"
        "  - name: dup\n    model: openai/gpt-4o\n"
        "  - name: dup\n    model: anthropic/claude-sonnet-4-5-20250929\n",
    )
    with pytest.raises(ModelCatalogError, match="duplicate model name"):
        load_model_catalog(*path)


def test_non_numeric_rating_raises(tmp_path):
    path = _list_only(
        tmp_path, "models:\n  - name: foo\n    model: openai/gpt-4o\n    ratings: {cost: high}\n"
    )
    with pytest.raises(ModelCatalogError, match="rating"):
        load_model_catalog(*path)


def test_ratings_not_a_mapping_raises(tmp_path):
    path = _list_only(
        tmp_path, "models:\n  - name: foo\n    model: openai/gpt-4o\n    ratings: [1, 2, 3]\n"
    )
    with pytest.raises(ModelCatalogError, match="'ratings'"):
        load_model_catalog(*path)


def test_task_profile_non_numeric_weight_raises(tmp_path):
    path = _list_only(
        tmp_path, "models:\n  - name: foo\n    model: openai/gpt-4o\n    ratings: {cost: 5}\n"
    )
    profiles = tmp_path / "task_profiles.yaml"
    profiles.write_text("task_profiles:\n  bogus:\n    weights: {cost: lots}\n")
    with pytest.raises(ModelCatalogError, match="weight"):
        load_model_catalog(*path, profiles_path=str(profiles))


# --- classify_task ---------------------------------------------------------


def _catalog_with_profiles(*profiles: TaskProfile) -> ModelCatalog:
    return ModelCatalog(
        models=[ModelCatalogEntry(name="x", model="openai/gpt-4o")],
        task_profiles=list(profiles),
    )


def test_classify_task_matches_a_trigger_case_insensitively():
    debugging = TaskProfile(name="debugging", triggers=("fix", "bug"), weights={"reasoning": 3})
    default = TaskProfile(name="default", weights={"reasoning": 1})
    catalog = _catalog_with_profiles(debugging, default)

    profile = classify_task("Please FIX the crash in the parser", catalog)

    assert profile.name == "debugging"


def test_classify_task_first_declared_match_wins():
    first = TaskProfile(name="first", triggers=("fix",), weights={"a": 1})
    second = TaskProfile(name="second", triggers=("fix",), weights={"a": 2})
    catalog = _catalog_with_profiles(first, second)

    profile = classify_task("please fix this", catalog)

    assert profile.name == "first"


def test_classify_task_falls_back_to_default_profile():
    debugging = TaskProfile(name="debugging", triggers=("fix",), weights={"reasoning": 3})
    default = TaskProfile(name="default", weights={"reasoning": 1})
    catalog = _catalog_with_profiles(debugging, default)

    profile = classify_task("Write a haiku about clouds", catalog)

    assert profile.name == "default"


def test_classify_task_with_no_default_profile_synthesizes_empty_weights():
    debugging = TaskProfile(name="debugging", triggers=("fix",), weights={"reasoning": 3})
    catalog = _catalog_with_profiles(debugging)

    profile = classify_task("Write a haiku about clouds", catalog)

    assert profile.weights == {}


def test_classify_task_matches_whole_words_only():
    debugging = TaskProfile(name="debugging", triggers=("fix",), weights={"reasoning": 3})
    default = TaskProfile(name="default", weights={"reasoning": 1})
    catalog = _catalog_with_profiles(debugging, default)

    assert classify_task("Add a --prefix option", catalog).name == "default"
    assert classify_task("Fix the prefix option", catalog).name == "debugging"


def test_classify_task_matches_a_simple_plural():
    debugging = TaskProfile(name="debugging", triggers=("bug", "crash"), weights={"a": 1})
    catalog = _catalog_with_profiles(debugging)

    assert classify_task("Two bugs in the parser", catalog).name == "debugging"
    assert classify_task("It crashes on empty input", catalog).name == "debugging"


def test_classify_task_reads_only_the_first_line_with_text():
    # A spec body that says "raise an error" or "fix all failures" must not
    # make a "build a game" task a debugging one.
    debugging = TaskProfile(name="debugging", triggers=("fix", "error"), weights={"a": 3})
    default = TaskProfile(name="default", weights={"a": 1})
    catalog = _catalog_with_profiles(debugging, default)
    task = "\n# Durations\n\nRaise ValueError on an error. Fix all failures.\n"

    assert task_title(task) == "Durations"
    assert classify_task(task, catalog).name == "default"
    assert find_trigger("# Fix the parser\nmore text", debugging) == "fix"


def test_a_milestone_is_classified_by_its_own_title_first():
    debugging = TaskProfile(name="debugging", triggers=("fix",), weights={"a": 3})
    build = TaskProfile(name="build", triggers=("game",), weights={"a": 2})
    default = TaskProfile(name="default", weights={"a": 1})
    catalog = _catalog_with_profiles(debugging, build, default)
    plan = parse_milestones(
        "# A platform game\n\n## Milestone 1: The level\n\nDraw it.\n\n"
        "## Milestone 2: Fix the flaky tests\n\nMake them pass.\n"
    )
    first, second = milestone_task(plan, 1), milestone_task(plan, 2)

    assert classification_titles(second) == ["Fix the flaky tests", "A platform game"]
    # Its own title has a trigger: it wins over the task's.
    assert classify_task(second, catalog).name == "debugging"
    assert find_trigger_in(second, debugging) == ("fix", "Fix the flaky tests")
    # No trigger in its own title: the task's title decides.
    assert classify_task(first, catalog).name == "build"
    assert find_trigger_in(first, build) == ("game", "A platform game")
    # A whole task is classified by its title alone, as before.
    assert classification_titles("# Fix it\n\n## Now: nothing") == ["Fix it"]


_BUNDLED_TASKS = Path(__file__).resolve().parent.parent / "src" / "certo"


@pytest.mark.parametrize(
    ("task_file", "expected"),
    [
        ("benchmark_tasks/duration-parser/task.md", "default"),
        ("benchmark_tasks/inventory-fix/task.md", "debugging"),
        ("benchmark_tasks/page-ranges/task.md", "default"),
        ("benchmark_tasks/pedestrian-crossing/task.md", "default"),
        ("benchmark_tasks/semver-order/task.md", "default"),
        ("benchmark_tasks/slugify/task.md", "default"),
        ("benchmark_tasks/temperature-table/task.md", "default"),
        ("benchmark_tasks/token-bucket/task.md", "default"),
        ("benchmark_tasks/wordle-score/task.md", "default"),
        ("starter/tasks/wordle.md", "default"),
        ("starter/tasks/space-rocks.md", "default"),
        ("starter/tasks/hanoi.md", "default"),
        ("starter/tasks/mazeman.md", "default"),
        ("starter/tasks/invaders.md", "default"),
        ("starter/tasks/sky-hopper.md", "build"),
        ("starter/tasks/iron-horizon.md", "build"),
        ("starter/tasks/team-board.md", "build"),
    ],
)
def test_shipped_profiles_classify_the_bundled_tasks(tmp_path, task_file, expected):
    # Until 2026-10-19, whole-text matching sent 12 of 14 real tasks to
    # `debugging` ("raise ValueError", "fix all failures" in the spec).
    examples = _BUNDLED_TASKS / "examples"
    example = examples / "models_list.yaml.example"
    names = [m["name"] for m in yaml.safe_load(example.read_text())["models"]]
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump({"models": [{"name": n} for n in names]}))
    catalog = load_model_catalog(
        str(example),
        str(models),
        profiles_path=str(examples / "task_profiles.yaml.example"),
        strict=False,
    )

    task = (_BUNDLED_TASKS / task_file).read_text()

    assert classify_task(task, catalog).name == expected


# --- a profile's pinned model ------------------------------------------------

_PINNED_YAML = """
models:
  - name: cheap
    model: openai/gpt-4o-mini
    ratings: {reasoning: 2, cost: 5}
  - name: strong
    model: anthropic/claude-opus-4
    ratings: {reasoning: 5, cost: 1}
  - name: parked
    model: openai/gpt-old
    ratings: {reasoning: 9, cost: 9}
    activated: false
task_profiles:
  debugging:
    triggers: [fix]
    model: MODEL
    weights: {cost: 1}
"""


def _pinned(tmp_path, model):
    catalog = load_model_catalog(
        **_catalog_files(tmp_path, _PINNED_YAML.replace("MODEL", model)), strict=False
    )
    return catalog, catalog.task_profiles[0]


def test_a_profile_can_name_a_model(tmp_path):
    _catalog, profile = _pinned(tmp_path, "strong")

    assert profile.model == "strong"


def test_a_profile_model_must_be_a_name(tmp_path):
    with pytest.raises(ModelCatalogError, match="'model' must be the name of a model"):
        load_model_catalog(**_catalog_files(tmp_path, _PINNED_YAML.replace("MODEL", "[a, b]")))


def test_the_pinned_model_goes_first_and_the_weights_order_the_rest(tmp_path):
    # The weights (cost only) would put `cheap` first.
    catalog, profile = _pinned(tmp_path, "strong")

    ranked, how = rank_for_profile(catalog, profile)

    assert [m.name for m in ranked] == ["strong", "cheap"]
    assert how == "the profile names strong; fallbacks ranked by weights"


@pytest.mark.parametrize(
    ("model", "why"),
    [("parked", "isn't enabled in models.yaml"), ("nonesuch", "isn't in models_list.yaml")],
)
def test_a_pinned_model_that_cant_run_falls_back_to_the_weights(tmp_path, model, why):
    catalog, profile = _pinned(tmp_path, model)

    ranked, how = rank_for_profile(catalog, profile)

    assert [m.name for m in ranked] == ["cheap", "strong"]
    assert how == f"the profile names {model}, which {why}; ranked by weights"


def test_without_a_pinned_model_the_weights_decide(tmp_path):
    catalog = load_model_catalog(
        **_catalog_files(tmp_path, _PINNED_YAML.replace("    model: MODEL\n", "")), strict=False
    )

    ranked, how = rank_for_profile(catalog, catalog.task_profiles[0])

    assert [m.name for m in ranked] == ["cheap", "strong"]
    assert how == "ranked by the profile's weights"


# --- score_entry / rank_candidates -----------------------------------------


def test_score_entry_is_a_weighted_sum():
    entry = ModelCatalogEntry(name="x", model="openai/gpt-4o", ratings={"reasoning": 4, "cost": 2})

    score = score_entry(entry, {"reasoning": 3, "cost": 1})

    assert score == 4 * 3 + 2 * 1


def test_score_entry_treats_a_missing_axis_as_zero():
    entry = ModelCatalogEntry(name="x", model="openai/gpt-4o", ratings={"reasoning": 4})

    score = score_entry(entry, {"reasoning": 1, "cost": 100})

    assert score == 4


def test_rank_candidates_sorts_descending_by_score():
    cheap = ModelCatalogEntry(name="cheap", model="a", ratings={"reasoning": 1, "cost": 5})
    smart = ModelCatalogEntry(name="smart", model="b", ratings={"reasoning": 5, "cost": 1})
    catalog = ModelCatalog(models=[cheap, smart], task_profiles=[])

    ranked = rank_candidates(catalog, {"reasoning": 1, "cost": 0})

    assert [e.name for e in ranked] == ["smart", "cheap"]


def test_rank_candidates_breaks_ties_by_declared_order():
    a = ModelCatalogEntry(name="a", model="x", ratings={"reasoning": 3})
    b = ModelCatalogEntry(name="b", model="y", ratings={"reasoning": 3})
    catalog = ModelCatalog(models=[a, b], task_profiles=[])

    ranked = rank_candidates(catalog, {"reasoning": 1})

    assert [e.name for e in ranked] == ["a", "b"]


def test_rank_candidates_works_with_a_single_model_catalog():
    only = ModelCatalogEntry(name="only", model="x", ratings={"reasoning": 3})
    catalog = ModelCatalog(models=[only], task_profiles=[])

    ranked = rank_candidates(catalog, {"reasoning": 1})

    assert ranked == [only]


def test_rank_candidates_excludes_deactivated_models():
    active = ModelCatalogEntry(name="active", model="x", ratings={"reasoning": 1})
    inactive = ModelCatalogEntry(
        name="inactive", model="y", ratings={"reasoning": 5}, activated=False
    )
    catalog = ModelCatalog(models=[active, inactive], task_profiles=[])

    ranked = rank_candidates(catalog, {"reasoning": 1})

    # inactive scores higher (5 vs 1) but must still be excluded entirely.
    assert ranked == [active]


def test_rank_candidates_raises_when_every_model_is_deactivated():
    only = ModelCatalogEntry(name="only", model="x", ratings={"reasoning": 3}, activated=False)
    catalog = ModelCatalog(models=[only], task_profiles=[])

    with pytest.raises(ModelCatalogError, match="activated"):
        rank_candidates(catalog, {"reasoning": 1})


# --- timeout_seconds -------------------------------------------------------------


def test_timeout_seconds_defaults_to_300_and_can_be_set(tmp_path):
    catalog = load_model_catalog(
        **_catalog_files(
            tmp_path,
            """
models:
  - name: cloud
    model: openai/gpt-4o
  - name: slow-local
    model: ollama/qwen3-coder:30b
    timeout_seconds: 1200
  - name: no-limit
    model: ollama/big
    timeout_seconds: 0
""",
        )
    )

    assert [m.timeout_seconds for m in catalog.models] == [300, 1200, 0]


@pytest.mark.parametrize("value", ["-1", "'600'", "1.5", "true"])
def test_timeout_seconds_must_be_a_whole_number_of_seconds(tmp_path, value):
    text = f"models:\n  - name: m\n    model: openai/gpt-4o\n    timeout_seconds: {value}\n"
    with pytest.raises(ModelCatalogError, match="timeout_seconds"):
        load_model_catalog(**_catalog_files(tmp_path, text))


# --- escalation section ----------------------------------------------------------

_TWO_MODELS = """
models:
  - name: local
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
    ratings: {code: 2, cost: 5}
  - name: cloud
    model: openai/gpt-4o
    api_key: sk-fake
    ratings: {code: 5, cost: 2}
"""


def test_no_escalation_section_gives_the_defaults(tmp_path):
    settings = load_model_catalog(**_catalog_files(tmp_path, _TWO_MODELS)).escalation

    assert settings.cost_axis == "cost"
    assert settings.cost_axis_set is False
    assert settings.max_rungs == 3
    assert settings.ladders == {}


def test_escalation_section_with_both_ladder_forms(tmp_path):
    text = (
        _TWO_MODELS
        + """
escalation:
  cost_axis: price
  max_rungs: 4
  ladders:
    default:
      - model: local
        retries: 1
        reasoning_effort: ""
      - model: cloud
    careful:
      escalate_on_acceptance_failed: true
      rungs:
        - model: local
          reasoning_effort: max
"""
    )
    settings = load_model_catalog(**_catalog_files(tmp_path, text)).escalation

    assert (settings.cost_axis, settings.cost_axis_set, settings.max_rungs) == ("price", True, 4)
    default = settings.ladders["default"]
    assert [r.model for r in default.rungs] == ["local", "cloud"]
    assert default.rungs[0].retries == 1
    assert default.rungs[0].reasoning_effort is None  # blank means the entry's own
    assert default.rungs[1].retries is None
    assert default.escalate_on_acceptance_failed is False
    careful = settings.ladders["careful"]
    assert careful.escalate_on_acceptance_failed is True
    assert careful.rungs[0].reasoning_effort == "max"


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("escalation: [a]", "'escalation' must be a mapping"),
        ("escalation: {colour: red}", "unknown key"),
        ("escalation: {max_rungs: 1}", "at least 2"),
        ("escalation: {max_rungs: two}", "at least 2"),
        ("escalation: {cost_axis: ''}", "cost_axis"),
        ("escalation: {ladders: [a]}", "mapping of name"),
        ("escalation: {ladders: {x: local}}", "list of rungs"),
        ("escalation: {ladders: {x: [local]}}", "each rung must be a mapping"),
        ("escalation: {ladders: {x: [{retries: 1}]}}", "'model'"),
        ("escalation: {ladders: {x: [{model: local, retries: 1.5}]}}", "'retries'"),
        ("escalation: {ladders: {x: [{model: local, colour: red}]}}", "unknown key"),
        ("escalation: {ladders: {x: {rungs: [], extra: 1}}}", "unknown key"),
        (
            "escalation: {ladders: {x: {rungs: [], escalate_on_acceptance_failed: 1}}}",
            "true or false",
        ),
    ],
)
def test_escalation_section_shape_errors(tmp_path, section, message):
    with pytest.raises(ModelCatalogError, match=message):
        load_model_catalog(**_catalog_files(tmp_path, _TWO_MODELS + section + "\n"))


def test_the_commented_ladders_in_the_escalation_example_parse(tmp_path):
    # Uncommenting the example's ladders must give a valid escalation.yaml.
    examples = Path(__file__).resolve().parent.parent / "src/certo/examples"
    text = (examples / "escalation.yaml.example").read_text()
    lines = []
    for line in text[text.index("escalation:") :].splitlines():
        if line.startswith("#   ") or line.startswith("#     "):
            lines.append(line[2:])
        elif not line.startswith("#"):
            lines.append(line)
    escalation = tmp_path / "escalation.yaml"
    escalation.write_text("\n".join(lines) + "\n")
    names = [
        m["name"]
        for m in yaml.safe_load((examples / "models_list.yaml.example").read_text())["models"]
    ]
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump({"models": [{"name": n} for n in names]}))

    catalog = load_model_catalog(
        str(examples / "models_list.yaml.example"), str(models), escalation_path=str(escalation)
    )

    assert list(catalog.escalation.ladders) == ["default", "local-only"]
    assert catalog.escalation.max_rungs == 3


# --- the two files: models_list.yaml and models.yaml ------------------------------

_LIST = """
models:
  - name: local
    model: ollama/qwen3-coder:30b
    timeout_seconds: 900
    ratings: {reasoning: 1, precision: 2, code: 1, cost: 5}
  - name: cloud
    model: openai/gpt-6-luna
    reasoning_effort: high
    description: Cheap cloud model.
    ratings: {reasoning: 3, precision: 3, code: 3, cost: 4}
  - name: unused
    model: anthropic/claude-sonnet-5-5
    ratings: {reasoning: 4, precision: 4, code: 5, cost: 2}
"""


def _files(tmp_path, personal: str, listed: str = _LIST) -> tuple[str, str]:
    (tmp_path / "models_list.yaml").write_text(listed)
    (tmp_path / "models.yaml").write_text(personal)
    return str(tmp_path / "models_list.yaml"), str(tmp_path / "models.yaml")


def test_models_yaml_picks_models_from_the_list_and_adds_personal_settings(tmp_path):
    catalog = load_model_catalog(
        *_files(
            tmp_path,
            "models:\n  - name: local\n    base_url: http://gpu-box:11434\n"
            "  - name: cloud\n    api_key: sk-mine\n    activated: false\n",
        )
    )
    local, cloud, unused = catalog.models
    assert (local.model, local.base_url, local.api_key) == (
        "ollama/qwen3-coder:30b",
        "http://gpu-box:11434",
        None,
    )
    assert (local.configured, local.activated, local.timeout_seconds) == (True, True, 900)
    assert (cloud.api_key, cloud.configured, cloud.activated) == ("sk-mine", True, False)
    # In the list only: known, never used.
    assert (unused.configured, unused.activated) == (False, False)


def test_overrides_replace_the_lists_values(tmp_path):
    catalog = load_model_catalog(
        *_files(
            tmp_path,
            "models:\n  - name: cloud\n    api_key: k\n    ratings: {code: 4}\n"
            "    reasoning_effort: max\n    timeout_seconds: 60\n    description: Mine.\n",
        )
    )
    cloud = catalog.models[1]
    # Ratings are replaced axis by axis.
    assert cloud.ratings == {"reasoning": 3, "precision": 3, "code": 4, "cost": 4}
    assert (cloud.reasoning_effort, cloud.timeout_seconds, cloud.description) == (
        "max",
        60,
        "Mine.",
    )


@pytest.mark.parametrize("key", ["api_key", "base_url", "activated"])
def test_personal_settings_in_the_list_are_an_error(tmp_path, key):
    listed = _LIST.replace("    timeout_seconds: 900\n", f"    {key}: x\n")
    with pytest.raises(ModelCatalogError, match=f"has {key}.*belong in models.yaml"):
        load_model_catalog(*_files(tmp_path, "models:\n  - name: local\n", listed))


@pytest.mark.parametrize(
    "personal",
    [
        "models:\n  - name: local\n    model: ollama/qwen3-coder:30b\n",
        "models:\n  - name: local\ntask_profiles: {}\n",
        "models:\n  - name: local\nescalation: {}\n",
    ],
)
def test_the_old_single_file_models_yaml_says_what_to_move(tmp_path, personal):
    with pytest.raises(ModelCatalogError, match="Since version 0.1.10.*models_list.yaml"):
        load_model_catalog(*_files(tmp_path, personal))


def test_a_name_missing_from_the_list(tmp_path):
    paths = _files(tmp_path, "models:\n  - name: claude\n")
    with pytest.raises(ModelCatalogError, match="'claude', which isn't in models_list.yaml"):
        load_model_catalog(*paths)
    assert load_model_catalog(*paths, strict=False).load_problems == (
        (
            "models.yaml names 'claude', which isn't in models_list.yaml. Check the spelling, or "
            "add the model to models_list.yaml."
        ),
    )


def test_a_name_listed_twice_in_models_yaml(tmp_path):
    paths = _files(tmp_path, "models:\n  - name: local\n  - name: local\n")
    assert (
        "models.yaml lists 'local' twice." in load_model_catalog(*paths, strict=False).load_problems
    )


@pytest.mark.parametrize(
    ("personal", "message"),
    [
        ("models: []\n", "non-empty 'models' list"),
        ("models:\n  - api_key: k\n", "'name'"),
        ("models:\n  - name: local\n    colour: red\n", "unknown key"),
        ("models:\n  - name: local\n    activated: maybe\n", "'activated'"),
    ],
)
def test_models_yaml_shape_errors(tmp_path, personal, message):
    with pytest.raises(ModelCatalogError, match=message):
        load_model_catalog(*_files(tmp_path, personal))


def test_the_shipped_examples_load_together():
    from pathlib import Path

    from certo.catalog_check import check_catalog

    examples = Path(__file__).resolve().parent.parent / "src/certo/examples"
    catalog = load_model_catalog(
        str(examples / "models_list.yaml.example"),
        str(examples / "models.yaml.example"),
        profiles_path=str(examples / "task_profiles.yaml.example"),
        escalation_path=str(examples / "escalation.yaml.example"),
        # The example names its keys as variables of the settings file.
        environ={"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-test"},
    )
    report = check_catalog(catalog)
    assert report.errors == []
    assert catalog.load_warnings == ()  # nothing left to move in the list
    assert catalog.task_profiles
    assert any(m.activated for m in catalog.models)
    assert any(not m.configured for m in catalog.models)


# --- task_profiles.yaml and escalation.yaml (0.1.20) -------------------------

_LAYOUT_YAML = """
models:
  - name: cheap
    model: openai/gpt-4o-mini
    ratings: {reasoning: 2, cost: 5}
  - name: strong
    model: anthropic/claude-opus-4
    ratings: {reasoning: 5, cost: 1}
task_profiles:
  debugging:
    triggers: [fix]
    weights: {reasoning: 3}
escalation:
  max_rungs: 2
  ladders:
    default:
      - model: cheap
      - model: strong
"""


def test_profiles_and_ladders_are_read_from_their_own_files(tmp_path):
    files = write_split_model_files(tmp_path, _LAYOUT_YAML)
    assert "task_profiles" not in Path(files["list_path"]).read_text()

    catalog = load_model_catalog(**files)

    assert [p.name for p in catalog.task_profiles] == ["debugging"]
    assert catalog.escalation.max_rungs == 2
    assert [r.model for r in catalog.escalation.ladders["default"].rungs] == ["cheap", "strong"]
    assert catalog.load_warnings == ()


@pytest.mark.parametrize(
    ("key", "own_file"),
    [("task_profiles", "task_profiles.yaml"), ("escalation", "escalation.yaml")],
)
def test_a_section_left_in_the_list_is_refused(tmp_path, key, own_file):
    # The layout before 0.1.20, read with a warning until 0.1.25.
    files = write_split_model_files(tmp_path, _LAYOUT_YAML)
    own = Path(files["profiles_path" if key == "task_profiles" else "escalation_path"])
    listed = Path(files["list_path"])
    listed.write_text(listed.read_text() + own.read_text())

    with pytest.raises(ModelCatalogError) as info:
        load_model_catalog(**files)  # even with the section's own file there

    assert (
        f"has the '{key}:' section. Since 0.1.20 it belongs in its own file, {own_file}, "
        "next to models_list.yaml, and since 0.1.26 it is no longer read here"
    ) in str(info.value)


@pytest.mark.parametrize(
    ("kwarg", "text"),
    [
        ("profiles_path", "task_profiles: {}\nmodels: []\n"),
        ("escalation_path", "escalation: {}\ntask_profiles: {}\n"),
    ],
)
def test_a_section_file_holds_only_its_section(tmp_path, kwarg, text):
    list_path, models_path = _write(tmp_path, _MINIMAL_YAML)
    extra = tmp_path / "extra.yaml"
    extra.write_text(text)

    with pytest.raises(ModelCatalogError, match="may only contain"):
        load_model_catalog(list_path, models_path, **{kwarg: str(extra)})


# --- ${VAR} in models.yaml -----------------------------------------------------------

_VAR_MODELS = """
models:
  - name: cloud
    model: anthropic/claude-haiku-5-5
    api_key: "${ANTHROPIC_API_KEY}"
    ratings: {code: 4}
  - name: local
    model: ollama/qwen3.8:27b
    base_url: "http://${OLLAMA_HOST_NAME}:11434"
    ratings: {code: 3}
"""


def _load_with(tmp_path, environ, models=_VAR_MODELS):
    list_path, models_path = write_model_files(tmp_path, models)
    return load_model_catalog(list_path, models_path, environ=environ)


def test_a_key_named_as_a_variable_is_read_from_the_settings(tmp_path):
    catalog = _load_with(
        tmp_path, {"ANTHROPIC_API_KEY": "sk-from-settings", "OLLAMA_HOST_NAME": "turing.local"}
    )
    by_name = {m.name: m for m in catalog.models}

    assert by_name["cloud"].api_key == "sk-from-settings"
    assert by_name["local"].base_url == "http://turing.local:11434"
    assert all(m.activated for m in catalog.models)
    assert catalog.load_warnings == ()


def test_a_model_whose_variable_is_unset_is_left_out_with_a_warning(tmp_path):
    # Before 0.1.21 the literal "${ANTHROPIC_API_KEY}" was sent as the key.
    catalog = _load_with(tmp_path, {"OLLAMA_HOST_NAME": "turing.local", "ANTHROPIC_API_KEY": " "})
    by_name = {m.name: m for m in catalog.models}

    assert by_name["cloud"].activated is False
    assert by_name["cloud"].api_key is None
    assert by_name["local"].activated is True
    assert catalog.load_warnings == (
        "models.yaml: 'cloud' has api_key ${ANTHROPIC_API_KEY}, which isn't set in your "
        "settings file or the environment, so this model is left out. Add "
        "ANTHROPIC_API_KEY=... to your settings file.",
    )


def test_an_unset_variable_on_a_model_already_switched_off_says_nothing(tmp_path):
    models = _VAR_MODELS.replace(
        "    ratings: {code: 4}", "    ratings: {code: 4}\n    activated: false"
    )
    catalog = _load_with(tmp_path, {"OLLAMA_HOST_NAME": "h"}, models=models)

    assert catalog.load_warnings == ()


def test_the_shipped_models_example_names_its_cloud_keys_as_variables():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parent.parent / "src/certo/examples/models.yaml.example"
    ).read_text()
    assert 'api_key: "${OPENAI_API_KEY}"' in text
    assert 'api_key: ""' not in text


def test_context_tokens_is_read_from_both_files_and_checked(tmp_path):
    from certo.model_catalog import ModelCatalogError, load_model_catalog

    listed = tmp_path / "models_list.yaml"
    listed.write_text(
        "models:\n  - name: q\n    model: ollama/q\n    context_tokens: 32768\n"
        "  - name: r\n    model: ollama/r\n"
    )
    mine = tmp_path / "models.yaml"
    mine.write_text("models:\n  - name: q\n  - name: r\n    context_tokens: 65536\n")

    catalog = load_model_catalog(str(listed), str(mine))

    assert {e.name: e.context_tokens for e in catalog.models} == {"q": 32768, "r": 65536}
    mine.write_text("models:\n  - name: q\n    context_tokens: lots\n")
    with pytest.raises(ModelCatalogError, match="'context_tokens' must be"):
        load_model_catalog(str(listed), str(mine))


# --- the cost rating follows the price -------------------------------------

_PRICE = re.compile(r"\$([0-9.]+) in\s*/\s*\$([0-9.]+) out")


def _cost_from_price(text: str) -> float:
    """The rubric in models_list.yaml.example: the blended price p per 1M
    tokens (3 input to 1 output), cost = 4 - log2(p) / 2, one decimal, kept
    between 1 and 4.9."""
    found = _PRICE.search(" ".join(text.split()))
    assert found, "no '$X in / $Y out' price in the description"
    price_in, price_out = (float(v) for v in found.groups())
    blended = (3 * price_in + price_out) / 4
    return round(min(4.9, max(1.0, 4 - math.log2(blended) / 2)), 1)


def test_every_cloud_models_cost_follows_its_price():
    example = _BUNDLED_TASKS / "examples" / "models_list.yaml.example"
    wrong = []
    for model in yaml.safe_load(example.read_text())["models"]:
        cost = model["ratings"]["cost"]
        if model["model"].startswith("ollama/"):
            if cost != 5:
                wrong.append(f"{model['name']}: local, cost {cost}, should be 5")
            continue
        expected = _cost_from_price(model["description"])
        if cost != expected:
            wrong.append(f"{model['name']}: cost {cost}, the price gives {expected}")
    assert wrong == []
