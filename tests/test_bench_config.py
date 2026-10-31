"""bench.yaml parsing, validation, and the strategy registry. No model."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from model_file_helpers import write_model_files

from certo import bench_strategies
from certo.bench_config import BenchConfigError, load_bench_config
from certo.bench_strategies import STRATEGIES, AttemptResult, RunContext, run_config
from certo.bench_tasks import load_tasks
from certo.config import DEFAULT_MAX_TASK_SECONDS, DEFAULT_TOOL_CALL_REMINDERS
from certo.model_files import example_path

_REPO = Path(__file__).resolve().parent.parent

MODELS = """
models:
  - name: local-coder
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
    timeout_seconds: 1200
  - name: cloud
    model: anthropic/claude-sonnet-5-5
    api_key: sk-test
    reasoning_effort: low
  - name: parked
    model: openai/gpt-4o
    api_key: sk-test
    activated: false
"""


def _write(tmp_path: Path, bench: str, models: str = MODELS) -> str:
    list_path, models_path = write_model_files(tmp_path, models)
    path = tmp_path / "bench.yaml"
    path.write_text(f"models_file: {models_path}\nmodels_list_file: {list_path}\n" + bench)
    return str(path)


VALID = """
tasks: all
repeats: 3
arms:
  - name: qwen-local
    strategy: single
    model: local-coder
  - name: sonnet
    strategy: single
    model: cloud
"""


def test_a_valid_file(tmp_path):
    cfg = load_bench_config(_write(tmp_path, VALID))
    assert cfg.repeats == 3
    assert [t.name for t in cfg.tasks] == [t.name for t in load_tasks()]
    assert [(a.name, a.strategy, a.models) for a in cfg.arms] == [
        ("qwen-local", "single", ["local-coder"]),
        ("sonnet", "single", ["cloud"]),
    ]


def test_an_arm_naming_an_inactive_model_is_an_error(tmp_path):
    bench = "arms:\n  - {name: a, strategy: single, model: parked}\n"
    with pytest.raises(BenchConfigError, match="'activated: false'.*Set 'activated: true'"):
        load_bench_config(_write(tmp_path, bench))


def test_models_yaml_warnings_are_kept_for_the_plan(tmp_path):
    models = MODELS.replace("    api_key: sk-test\n    reasoning_effort: low\n", "")
    cfg = load_bench_config(_write(tmp_path, VALID, models))
    assert any("'cloud' has no api_key and no base_url" in w for w in cfg.catalog_warnings)


def test_a_models_yaml_error_stops_the_benchmark(tmp_path):
    models = MODELS + "  - name: cloud\n    model: openai/gpt-4o\n"
    with pytest.raises(BenchConfigError, match="Two models in models_list.yaml are named 'cloud'"):
        load_bench_config(_write(tmp_path, VALID, models))


def test_a_task_list_and_default_repeats(tmp_path):
    bench = "tasks: [page-ranges, slugify]\narms:\n  - {name: a, strategy: single, model: cloud}\n"
    cfg = load_bench_config(_write(tmp_path, bench))
    assert [t.name for t in cfg.tasks] == ["page-ranges", "slugify"]
    assert cfg.repeats == 1


def test_unknown_model_lists_the_catalog_names(tmp_path):
    bench = "arms:\n  - {name: a, strategy: single, model: gpt-9}\n"
    with pytest.raises(BenchConfigError, match="unknown model 'gpt-9'.*has: cloud, local-coder"):
        load_bench_config(_write(tmp_path, bench))


def test_unknown_strategy_lists_the_known_ones(tmp_path):
    bench = "arms:\n  - {name: a, strategy: cascade, models: [cloud]}\n"
    with pytest.raises(
        BenchConfigError,
        match="unknown strategy 'cascade'.*Known strategies: auto, escalate, single",
    ):
        load_bench_config(_write(tmp_path, bench))


@pytest.mark.parametrize(
    "bench, message",
    [
        ("arms: []\n", "'arms' must be a non-empty list"),
        ("repeats: 0\narms:\n  - {name: a, strategy: single, model: cloud}\n", "'repeats'"),
        ("repeats: true\narms:\n  - {name: a, strategy: single, model: cloud}\n", "'repeats'"),
        ("tasks: [nope]\narms:\n  - {name: a, strategy: single, model: cloud}\n", "unknown task"),
        ("tasks: 3\narms:\n  - {name: a, strategy: single, model: cloud}\n", "'tasks' must be"),
        ("arms:\n  - {name: 'a b', strategy: single, model: cloud}\n", "needs a 'name'"),
        (
            (
                "arms:\n  - {name: a, strategy: single, model: cloud}\n"
                "  - {name: a, strategy: single, model: cloud}\n"
            ),
            "two arms are named 'a'",
        ),
        ("arms:\n  - {name: a, strategy: single}\n", "'model' must be a model name"),
        ("arms:\n  - {name: a, strategy: single, model: cloud, n: 3}\n", "unknown key"),
        ("arms:\n  - {name: a, strategy: single, model: cloud}\nrepeat: 2\n", "unknown key"),
    ],
)
def test_invalid_files_name_the_problem(tmp_path, bench, message):
    with pytest.raises(BenchConfigError, match=message):
        load_bench_config(_write(tmp_path, bench))


def test_missing_bench_file_prints_the_cp_command_for_the_shipped_example(tmp_path):
    # The example ships inside the package (certo/examples/), so the command
    # works after a pip install too.
    target = tmp_path / "bench.yaml"
    with pytest.raises(BenchConfigError) as info:
        load_bench_config(str(target))
    example = example_path("bench.yaml")
    assert Path(example).is_file()
    assert f"cp {example} {target}" in str(info.value)


def test_a_missing_named_models_file(tmp_path):
    path = tmp_path / "bench.yaml"
    path.write_text(f"models_file: {tmp_path / 'nope.yaml'}\narms: []\n")
    with pytest.raises(BenchConfigError, match="'models_file' names .*nope.yaml"):
        load_bench_config(str(path))


def test_no_model_files_says_what_to_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "bench.yaml"
    path.write_text("arms: []\n")
    with pytest.raises(BenchConfigError, match="models.yaml.example"):
        load_bench_config(str(path))


def test_the_model_files_are_found_in_the_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_model_files(tmp_path, MODELS)
    (tmp_path / "bench.yaml").write_text("arms:\n  - {name: a, strategy: single, model: cloud}\n")
    cfg = load_bench_config("bench.yaml")
    assert cfg.models_list_file == str((tmp_path / "models_list.yaml").resolve())


def test_an_escalation_file_can_be_named(tmp_path):
    list_path, models_path = write_model_files(tmp_path, MODELS)
    escalation = tmp_path / "escalation.yaml"
    escalation.write_text("escalation:\n  max_rungs: 2\n")
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        f"escalation_file: {escalation}\n"
        "arms:\n  - {name: a, strategy: single, model: cloud}\n"
    )

    cfg = load_bench_config(str(path))

    assert cfg.escalation_file == str(escalation.resolve())
    assert cfg.model_catalog.escalation.max_rungs == 2


def test_a_missing_escalation_file_is_an_error(tmp_path):
    list_path, models_path = write_model_files(tmp_path, MODELS)
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        "escalation_file: ./nope.yaml\narms:\n  - {name: a, strategy: single, model: cloud}\n"
    )

    with pytest.raises(BenchConfigError, match="'escalation_file' names './nope.yaml'"):
        load_bench_config(str(path))


def test_an_arm_naming_a_model_missing_from_models_yaml(tmp_path):
    list_path, models_path = write_model_files(tmp_path, MODELS)
    Path(models_path).write_text("models:\n  - name: cloud\n    api_key: k\n")
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n"
        "arms:\n  - {name: a, strategy: single, model: local-coder}\n"
    )
    with pytest.raises(BenchConfigError, match="in models_list.yaml but not in models.yaml"):
        load_bench_config(str(path))


def test_the_shipped_example_is_valid_against_the_shipped_models_example(tmp_path, monkeypatch):
    # Both shipped model examples as they are: copying the three examples
    # must give a benchmark file that loads, once the keys they name are
    # in the settings.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    text = (_REPO / "src/certo/examples/bench.yaml.example").read_text()
    list_path = _REPO / "src/certo/examples/models_list.yaml.example"
    models_path = _REPO / "src/certo/examples/models.yaml.example"
    path = tmp_path / "bench.yaml"
    path.write_text(f"models_file: {models_path}\nmodels_list_file: {list_path}\n" + text)
    cfg = load_bench_config(str(path))
    assert [a.strategy for a in cfg.arms] == ["single", "single", "escalate"]


@pytest.mark.parametrize(
    "bench_file", sorted((_REPO / "docs/benchmark").glob("bench-*.yaml")), ids=lambda p: p.name
)
def test_the_published_benchmark_files_load_against_the_shipped_catalog(tmp_path, bench_file):
    # docs/benchmark/*.yaml reproduce the published results: each must still
    # load once every model of the shipped models_list.yaml is enabled.
    import yaml

    list_path = _REPO / "src/certo/examples/models_list.yaml.example"
    catalog = yaml.safe_load(list_path.read_text())
    models = [
        {"name": m["name"], "base_url": "http://localhost:11434"}
        if m["model"].startswith("ollama/")
        else {"name": m["name"], "api_key": "sk-test"}
        for m in catalog["models"]
    ]
    models_path = tmp_path / "models.yaml"
    models_path.write_text(yaml.safe_dump({"models": models}))
    path = tmp_path / "bench.yaml"
    path.write_text(
        f"models_file: {models_path}\nmodels_list_file: {list_path}\n" + bench_file.read_text()
    )
    cfg = load_bench_config(str(path))
    assert cfg.arms


def test_run_config_takes_everything_from_the_catalog_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/should-not-be-used")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "sk-env")
    cfg = load_bench_config(_write(tmp_path, VALID))
    local = run_config(cfg.catalog["local-coder"], "/ws", "/iso")
    assert (local.model, local.api_key, local.base_url) == (
        "ollama/qwen3-coder:30b",
        None,
        "http://localhost:11434",
    )
    cloud = run_config(cfg.catalog["cloud"], "/ws", "/iso")
    assert (cloud.model, cloud.api_key, cloud.base_url, cloud.reasoning_effort) == (
        "anthropic/claude-sonnet-5-5",
        "sk-test",
        None,
        "low",
    )
    assert cloud.workspace == "/ws"
    assert (local.llm_timeout_seconds, cloud.llm_timeout_seconds) == (1200, 300)
    assert cloud.global_skills_dir.startswith("/iso")
    assert (cloud.model_selection, cloud.confirm_mode, cloud.interactive) == (
        "manual",
        "never",
        False,
    )


def test_single_strategy_runs_the_normal_pipeline_with_the_arm_model(tmp_path):
    cfg = load_bench_config(_write(tmp_path, VALID))
    seen = {}

    def fake_stream(task, *, cfg):
        seen.update(task=task, model=cfg.model)
        return SimpleNamespace(
            verification_state="verified", retries_used=1, tool_call_reminders=2, run_summary=None
        )

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream)
    result = STRATEGIES["single"].run(ctx, cfg.arms[1].params)
    assert seen == {"task": "do it", "model": "anthropic/claude-sonnet-5-5"}
    assert result == AttemptResult("verified", 1, None, ("cloud",), tool_call_reminders=2)


def test_single_strategy_defaults_tool_call_reminders_when_the_outcome_lacks_it(tmp_path):
    """A fake outcome from an older test, or one that never names the field,
    still gets a real AttemptResult: a missing count is 0, not an error."""
    cfg = load_bench_config(_write(tmp_path, VALID))

    def fake_stream(task, *, cfg):
        return SimpleNamespace(verification_state="verified", retries_used=0, run_summary=None)

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream)
    result = STRATEGIES["single"].run(ctx, cfg.arms[1].params)
    assert result.tool_call_reminders == 0


def test_a_new_strategy_is_one_registry_entry(tmp_path, monkeypatch):
    """The design promise: adding e.g. best_of needs no change elsewhere."""

    class BestOf:
        name = "best_of"
        description = "test only"

        def parse(self, arm, catalog, where):
            bench_strategies.reject_unknown_keys(arm, {"model", "n"}, where)
            return {
                "model": bench_strategies.model_name(arm, "model", catalog, where),
                "n": arm["n"],
            }

        def models(self, params):
            return [params["model"]]

        def run(self, ctx, params):
            raise NotImplementedError

    monkeypatch.setitem(STRATEGIES, "best_of", BestOf())
    bench = "arms:\n  - {name: b, strategy: best_of, model: cloud, n: 3}\n"
    cfg = load_bench_config(_write(tmp_path, bench))
    assert cfg.arms[0].params == {"model": "cloud", "n": 3}
    assert cfg.arms[0].models == ["cloud"]


# --- strategy: escalate ---------------------------------------------------------------

ESCALATE = """
arms:
  - name: local-then-cloud
    strategy: escalate
    models: [local-coder, cloud]
  - name: derived
    strategy: escalate
"""


def test_escalate_arms_explicit_and_derived(tmp_path):
    cfg = load_bench_config(_write(tmp_path, ESCALATE))
    explicit, derived = cfg.arms
    assert explicit.params == {"models": ["local-coder", "cloud"]}
    assert explicit.models == ["local-coder", "cloud"]
    # A derived arm may use every active model; 'parked' is inactive.
    assert derived.models == ["local-coder", "cloud"]
    assert cfg.model_catalog is not None


@pytest.mark.parametrize(
    ("arm", "message"),
    [
        ("{name: a, strategy: escalate, models: [cloud]}", "at least two models"),
        ("{name: a, strategy: escalate, models: cloud}", "at least two models"),
        ("{name: a, strategy: escalate, models: [cloud, cloud]}", "lists a model twice"),
        ("{name: a, strategy: escalate, models: [cloud, nope]}", "unknown model 'nope'"),
        ("{name: a, strategy: escalate, models: [cloud, parked]}", "'activated: false'"),
        ("{name: a, strategy: escalate, model: cloud}", "unknown key"),
    ],
)
def test_escalate_arm_errors(tmp_path, arm, message):
    with pytest.raises(BenchConfigError, match=message):
        load_bench_config(_write(tmp_path, f"arms:\n  - {arm}\n"))


def _escalation_outcome(final_rung, names):
    from certo.escalation import RungResult

    rungs = tuple(
        RungResult(
            n, name, f"x/{name}", "verified" if n == final_rung else "no_progress", 1, 1.0, None
        )
        for n, name in enumerate(names, start=1)
    )
    return SimpleNamespace(
        verification_state="verified",
        retries_used=0,
        tool_call_reminders=sum(r.tool_call_reminders for r in rungs),
        run_summary=None,
        rungs=rungs,
        final_rung=final_rung,
    )


def test_escalate_strategy_runs_an_explicit_ladder(tmp_path):
    cfg = load_bench_config(_write(tmp_path, ESCALATE))
    seen = {}

    def fake_stream(task, *, cfg, ladder):
        seen.update(model=cfg.model, kind=ladder.kind, rungs=[r.name for r in ladder.rungs])
        return _escalation_outcome(2, ["local-coder", "cloud"])

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    result = STRATEGIES["escalate"].run(ctx, cfg.arms[0].params)

    assert seen == {
        "model": "ollama/qwen3-coder:30b",
        "kind": "explicit",
        "rungs": ["local-coder", "cloud"],
    }
    assert result.models_used == ("local-coder", "cloud")
    assert result.final_rung == 2
    assert [(r["name"], r["final"]) for r in result.rungs] == [
        ("local-coder", False),
        ("cloud", True),
    ]
    assert result.tool_call_reminders == 0


def test_escalate_strategy_sums_tool_call_reminders_over_every_rung(tmp_path):
    from certo.escalation import RungResult

    cfg = load_bench_config(_write(tmp_path, ESCALATE))
    rungs = (
        RungResult(1, "local-coder", "x/l", "no_progress", 1, 1.0, None, tool_call_reminders=2),
        RungResult(2, "cloud", "x/c", "verified", 0, 1.0, None, tool_call_reminders=1),
    )
    outcome = SimpleNamespace(
        verification_state="verified",
        retries_used=0,
        tool_call_reminders=sum(r.tool_call_reminders for r in rungs),
        run_summary=None,
        rungs=rungs,
        final_rung=2,
    )

    def fake_stream(task, *, cfg, ladder):
        return outcome

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    result = STRATEGIES["escalate"].run(ctx, cfg.arms[0].params)

    assert result.tool_call_reminders == 3


def test_escalate_strategy_derives_a_ladder_per_task(tmp_path):
    cfg = load_bench_config(_write(tmp_path, ESCALATE))
    seen = {}

    def fake_stream(task, *, cfg, ladder):
        seen.update(kind=ladder.kind, rungs=[r.name for r in ladder.rungs])
        return _escalation_outcome(1, [ladder.rungs[0].name])

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    STRATEGIES["escalate"].run(ctx, cfg.arms[1].params)

    assert seen["kind"] == "derived"
    assert "parked" not in seen["rungs"]


def test_an_arm_on_a_model_whose_key_variable_is_unset_says_which(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    text = (_REPO / "src/certo/examples/bench.yaml.example").read_text()
    list_path = _REPO / "src/certo/examples/models_list.yaml.example"
    models_path = _REPO / "src/certo/examples/models.yaml.example"
    path = tmp_path / "bench.yaml"
    path.write_text(f"models_file: {models_path}\nmodels_list_file: {list_path}\n" + text)

    with pytest.raises(BenchConfigError, match=r"uses \$\{OPENAI_API_KEY\} in models.yaml"):
        load_bench_config(str(path))


def test_a_bench_run_never_gets_the_users_global_skills(tmp_path, monkeypatch):
    from certo import skill_library as lib

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    lib.global_dir().mkdir(parents=True)
    (lib.global_dir() / "my-style.md").write_text("---\nname: my-style\n---\nMine.\n")
    cfg = load_bench_config(_write(tmp_path, VALID))

    run = run_config(cfg.catalog["cloud"], str(tmp_path / "ws"), str(tmp_path / "iso"))

    assert run.global_skills_dir == str(tmp_path / "iso" / "global_skills")
    assert "my-style" not in {s.name for s in lib.collect(run, run.workspace).skills}


INDEPENDENT = """
tasks: all
arms:
  - {name: with, strategy: single, model: cloud, independent_tests: true}
  - {name: without, strategy: single, model: cloud, independent_tests: false}
  - {name: ladder, strategy: escalate, models: [local-coder, cloud], independent_tests: true}
"""


def test_independent_tests_is_an_option_of_every_arm(tmp_path):
    with_, without, ladder = load_bench_config(_write(tmp_path, INDEPENDENT)).arms
    assert with_.params == {"model": "cloud", "independent_tests": True}
    # Off is left out, so a results folder from before the option still
    # matches on --resume.
    assert without.params == {"model": "cloud"}
    assert ladder.params == {"models": ["local-coder", "cloud"], "independent_tests": True}


def test_independent_tests_must_be_true_or_false(tmp_path):
    bench = "arms:\n  - {name: a, strategy: single, model: cloud, independent_tests: 'yes'}\n"
    with pytest.raises(BenchConfigError, match="'independent_tests' must be true or false"):
        load_bench_config(_write(tmp_path, bench))


def test_an_independent_tests_arm_turns_them_on_in_the_run(tmp_path):
    cfg = load_bench_config(_write(tmp_path, INDEPENDENT))
    seen = []
    result_of_tests = SimpleNamespace(status="failed")

    def fake_stream(task, *, cfg, ladder=None):
        seen.append(cfg.independent_tests)
        return SimpleNamespace(
            verification_state="verified",
            retries_used=0,
            run_summary=None,
            independent_tests=result_of_tests,
            rungs=(),
            final_rung=None,
        )

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    with_, without, ladder = cfg.arms
    assert STRATEGIES["single"].run(ctx, with_.params).independent_tests is result_of_tests
    STRATEGIES["single"].run(ctx, without.params)
    STRATEGIES["escalate"].run(ctx, ladder.params)
    assert seen == [True, False, True]


CONTEXT = """
tasks: all
arms:
  - {name: small, strategy: single, model: cloud, context_tokens: 32768}
  - {name: small-raw, strategy: single, model: cloud, context_tokens: 32768, condense: false}
  - {name: plain, strategy: single, model: cloud, condense: true}
"""


def test_context_tokens_and_condense_are_arm_options(tmp_path):
    small, raw, plain = load_bench_config(_write(tmp_path, CONTEXT)).arms
    assert small.params == {"model": "cloud", "context_tokens": 32768}
    assert raw.params == {"model": "cloud", "context_tokens": 32768, "condense": False}
    assert plain.params == {"model": "cloud"}  # defaults left out, for --resume


def test_the_arm_options_reach_the_run(tmp_path):
    cfg = load_bench_config(_write(tmp_path, CONTEXT))
    seen = []

    def fake_stream(task, *, cfg, ladder=None):
        seen.append((cfg.llm_context_tokens, cfg.condense))
        return SimpleNamespace(verification_state="verified", retries_used=0, run_summary=None)

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    for arm in cfg.arms:
        STRATEGIES["single"].run(ctx, arm.params)
    assert seen == [(32768, True), (32768, False), (0, True)]


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ("context_tokens: 8192", "at least 16,384"),
        ("context_tokens: big", "must be a whole number"),
        ("condense: 'no'", "'condense' must be true or false"),
    ],
)
def test_bad_arm_options_are_refused(tmp_path, option, message):
    bench = f"arms:\n  - {{name: a, strategy: single, model: cloud, {option}}}\n"
    with pytest.raises(BenchConfigError, match=message):
        load_bench_config(_write(tmp_path, bench))


BUDGET = """
tasks: all
arms:
  - {name: slow, strategy: single, model: cloud, max_task_seconds: 3600}
  - {name: ladder, strategy: escalate, models: [local-coder, cloud], max_task_seconds: 5400}
  - {name: plain, strategy: single, model: cloud}
"""


def test_max_task_seconds_is_an_arm_option_for_every_strategy(tmp_path):
    cfg = load_bench_config(_write(tmp_path, BUDGET))
    slow, ladder, plain = cfg.arms
    assert slow.params == {"model": "cloud", "max_task_seconds": 3600}
    assert ladder.params["max_task_seconds"] == 5400
    assert plain.params == {"model": "cloud"}  # left out at its default, for --resume
    seen = []

    def fake_stream(task, *, cfg, ladder=None):
        seen.append(cfg.max_task_seconds)
        return SimpleNamespace(
            verification_state="verified",
            retries_used=0,
            run_summary=None,
            rungs=(),
            final_rung=None,
        )

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    for arm in cfg.arms:
        STRATEGIES[arm.strategy].run(ctx, arm.params)
    assert seen == [3600, 5400, DEFAULT_MAX_TASK_SECONDS]


def test_tool_call_reminders_is_an_arm_option(tmp_path):
    bench = (
        "arms:\n"
        "  - {name: no-reminders, strategy: single, model: cloud, tool_call_reminders: 0}\n"
        "  - {name: plain, strategy: single, model: cloud}\n"
    )
    cfg = load_bench_config(_write(tmp_path, bench))
    off, plain = cfg.arms
    assert off.params == {"model": "cloud", "tool_call_reminders": 0}
    assert plain.params == {"model": "cloud"}  # left out at its default, for --resume
    seen = []

    def fake_stream(task, *, cfg, ladder=None):
        seen.append(cfg.tool_call_reminders)
        return SimpleNamespace(
            verification_state="verified",
            retries_used=0,
            run_summary=None,
            rungs=(),
            final_rung=None,
        )

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    for arm in cfg.arms:
        STRATEGIES[arm.strategy].run(ctx, arm.params)
    assert seen == [0, DEFAULT_TOOL_CALL_REMINDERS]


def test_skills_off_is_an_arm_option(tmp_path):
    bench = (
        "arms:\n"
        "  - {name: bare, strategy: single, model: cloud, skills_off: [security-review]}\n"
        "  - {name: plain, strategy: single, model: cloud}\n"
    )
    cfg = load_bench_config(_write(tmp_path, bench))
    bare, plain = cfg.arms
    assert bare.params == {"model": "cloud", "skills_off": ["security-review"]}
    assert plain.params == {"model": "cloud"}  # left out when empty, for --resume
    seen = []

    def fake_stream(task, *, cfg, ladder=None):
        seen.append(cfg.skills_off)
        return SimpleNamespace(
            verification_state="verified",
            retries_used=0,
            run_summary=None,
            rungs=(),
            final_rung=None,
        )

    ctx = RunContext("do it", "/ws", cfg.catalog, "/iso", fake_stream, cfg.model_catalog)
    for arm in cfg.arms:
        STRATEGIES[arm.strategy].run(ctx, arm.params)
    assert seen == [("security-review",), ()]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("[no-such-skill]", "names no official skill: no-such-skill"),
        ("security-review", "must be a list of skill names"),
        ("[1]", "must be a list of skill names"),
    ],
)
def test_a_bad_skills_off_is_refused(tmp_path, value, message):
    bench = f"arms:\n  - {{name: a, strategy: single, model: cloud, skills_off: {value}}}\n"
    with pytest.raises(BenchConfigError, match=message):
        load_bench_config(_write(tmp_path, bench))


@pytest.mark.parametrize("value", ["-1", "'3'", "true", "1.5"])
def test_a_bad_tool_call_reminders_is_refused(tmp_path, value):
    bench = (
        f"arms:\n  - {{name: a, strategy: single, model: cloud, tool_call_reminders: {value}}}\n"
    )
    with pytest.raises(BenchConfigError, match="'tool_call_reminders' must be a whole number"):
        load_bench_config(_write(tmp_path, bench))


@pytest.mark.parametrize("value", ["0", "-5", "'1h'", "true", "1.5"])
def test_a_bad_max_task_seconds_is_refused(tmp_path, value):
    bench = f"arms:\n  - {{name: a, strategy: single, model: cloud, max_task_seconds: {value}}}\n"
    with pytest.raises(BenchConfigError, match="'max_task_seconds' must be a whole number"):
        load_bench_config(_write(tmp_path, bench))


def test_context_tokens_is_for_single_arms_only(tmp_path):
    bench = (
        "arms:\n  - {name: a, strategy: escalate, models: [local-coder, cloud], "
        "context_tokens: 32768}\n"
    )
    with pytest.raises(BenchConfigError, match="strategy 'single' only"):
        load_bench_config(_write(tmp_path, bench))
