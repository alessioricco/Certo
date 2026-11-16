"""computed_ratings.py and `certo models refresh`: ratings computed from the
model data, written to ratings.yaml and read by runs as a layer. No
network: the downloads are a fake opener."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from types import SimpleNamespace

import pytest

from certo import computed_ratings as cr
from certo.init_cmd import Prompter
from certo.model_catalog import load_model_catalog
from certo.model_data import build, dumps, parse
from certo.model_files import certo_file, find_layers
from certo.models_cmd import build_parser, refresh_main


def _data(generated="2026-11-16"):
    lmarena = {
        "webdev": [
            {"model_name": "Claude Haiku 5.5", "rating": 1593.0, "category": "overall"},
            {"model_name": "Qwen3.8-27B", "rating": 1590.0, "category": "overall"},
        ],
        "agent": [
            {
                "model_name": "Claude Haiku 5.5",
                "category": "overall",
                "cost_per_task_p50": 0.08,
                "session_count": 50,
            }
        ],
    }
    eci = [{"Model": "Claude Haiku 5.5", "eci": "160"}]
    return build(lmarena, eci, {}, {}, generated)


def _entry(name, model, base_url=None):
    return SimpleNamespace(name=name, model=model, base_url=base_url)


def test_own_results_point_code_at_the_share_of_runs_that_ended_verified():
    rows = [
        {"model": "anthropic/claude-haiku-5-5", "kind": "task", "verdict": "verified"},
        {"model": "anthropic/claude-haiku-5-5", "kind": "milestone", "verdict": "verified"},
        {"model": "anthropic/claude-haiku-5-5", "kind": "bench", "verdict": "failed"},
        {"model": "anthropic/claude-haiku-5-5", "kind": "planning", "verdict": "verified"},
        {"model": "ollama/qwen3.8:27b", "kind": "task", "verdict": "failed"},
        # Limits, interrupts and undecided checks say nothing about the work.
        {"model": "ollama/qwen3.8:27b", "kind": "task", "verdict": "budget_exhausted"},
        {"model": "ollama/qwen3.8:27b", "kind": "task", "verdict": "cost_exhausted"},
        {"model": "ollama/qwen3.8:27b", "kind": "task", "verdict": "inconclusive"},
        {"model": "ollama/qwen3.8:27b", "kind": "task", "verdict": "interrupted"},
    ]
    own = cr.own_results(rows)
    assert own["anthropic/claude-haiku-5-5"] == (pytest.approx(1 + 4 * 2 / 3), 3)
    assert own["ollama/qwen3.8:27b"] == (1.0, 1)


def test_every_model_is_rated_with_its_price_and_a_model_no_source_has_says_so():
    data = parse(dumps(_data()))
    prices = {"claude-haiku-5-5": {"input_cost_per_token": 1e-7, "output_cost_per_token": 5e-7}}
    rows = cr.compute(
        [
            _entry("claude-haiku-5-5", "anthropic/claude-haiku-5-5"),
            _entry("qwen3.8-27b-local", "ollama/qwen3.8:27b"),
            _entry("flint-40b-local", "ollama/flint:40b"),
        ],
        data,
        {"anthropic/claude-haiku-5-5": (5.0, 13)},
        prices,
    )
    haiku, qwen, flint = rows
    assert haiku.price == (0.1, 0.5)  # the current list, $ per 1M tokens
    assert haiku.rated.ratings["code"] == 4.4  # 3.4 from the arena, lifted by 13 own runs
    assert haiku.rated.ratings["cost"] == 4.8  # from the cost per agent task
    assert qwen.local and qwen.price is None and qwen.rated.ratings["code"] == 2.4
    assert flint.rated.no_data and flint.rated.ratings == {"cost": 5.0, "speed": 2.0}


def test_the_file_reads_back_and_a_broken_one_reads_as_none(tmp_path):
    data = parse(dumps(_data()))
    rows = cr.compute([_entry("claude-haiku-5-5", "anthropic/claude-haiku-5-5")], data, {}, None)
    source = cr.DataSource(data, "this Certo version")
    path = tmp_path / "ratings.yaml"
    path.write_text(cr.render(rows, source, "2026-11-16"), encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Written by `certo models refresh` on 2026-11-16")
    assert "CC-BY-4.0" in text
    computed = cr.read_computed(str(path))
    assert computed["claude-haiku-5-5"].model == "anthropic/claude-haiku-5-5"
    assert computed["claude-haiku-5-5"].ratings["code"] == 3.4
    path.write_text("models: [oops", encoding="utf-8")
    assert cr.read_computed(str(path)) == {}
    assert cr.read_computed(str(tmp_path / "none.yaml")) == {}


def test_computed_ratings_replace_certos_but_never_the_users_or_another_model(tmp_path):
    path = tmp_path / "ratings.yaml"
    path.write_text(
        "models:\n"
        "- {name: a, model: x/a, ratings: {code: 4.4, cost: 4.8}}\n"
        "- {name: b, model: x/other, ratings: {code: 1.0}}\n",
        encoding="utf-8",
    )
    raw = {
        "models": [
            {"name": "a", "model": "x/a", "ratings": {"code": 3, "reasoning": 3, "cost": 4}},
            {"name": "b", "model": "x/b", "ratings": {"code": 3}},
        ]
    }
    out = cr.apply_computed(raw, {"a": {"cost": 2}}, str(path))
    assert out["models"][0]["ratings"] == {"code": 4.4, "reasoning": 3, "cost": 2}
    assert out["models"][1]["ratings"] == {"code": 3}  # another id: not this model


def _write_ratings(model="anthropic/claude-haiku-5-5", code=4.4):
    path = cr.ratings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f"models:\n- {{name: claude-haiku-5-5, model: {model}, ratings: {{code: {code}}}}}\n"
        )
    return path


def _models_yaml(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("models:\n- {name: claude-haiku-5-5}\n", encoding="utf-8")
    return str(path)


def test_runs_read_the_refreshed_ratings_on_certos_list_and_the_users_still_win(tmp_path):
    path = _write_ratings()
    try:
        catalog = load_model_catalog(certo_file("models_list.yaml"), _models_yaml(tmp_path))
        haiku = next(m for m in catalog.models if m.name == "claude-haiku-5-5")
        assert haiku.ratings["code"] == 4.4
        # A user's own list layer gives code: it wins.
        mine = tmp_path / "models_list.yaml"
        mine.write_text("models:\n- {name: claude-haiku-5-5, ratings: {code: 2}}\n")
        layered = find_layers("models_list.yaml", project_dir=str(tmp_path))
        haiku = next(
            m
            for m in load_model_catalog(layered, _models_yaml(tmp_path)).models
            if m.name == "claude-haiku-5-5"
        )
        assert haiku.ratings["code"] == 2.0
        # A list a setting names (a benchmark's) is read alone, as written.
        alone = tmp_path / "pinned.yaml"
        alone.write_text(
            "models:\n- {name: claude-haiku-5-5, model: anthropic/claude-haiku-5-5, "
            "ratings: {code: 3}}\n"
        )
        haiku = load_model_catalog(str(alone), _models_yaml(tmp_path)).models[0]
        assert haiku.ratings["code"] == 3.0
    finally:
        os.remove(path)


class _Opener:
    """The network: what each URL returns, or the error it raises."""

    def __init__(self, data=None, prices=None):
        self.data, self.prices, self.urls = data, prices, []

    def __call__(self, url):
        self.urls.append(url)
        answer = self.data if url == cr.LATEST_DATA_URL else self.prices
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer).encode()


def test_the_latest_releases_data_is_cached_and_used_when_newer(tmp_path):
    cache = str(tmp_path / "cache" / "model_data.json")
    newer = _data(generated="2099-01-01")
    source = cr.newest_data(cache, _Opener(data=newer))
    assert (source.data.generated, source.where) == ("2099-01-01", "the latest release")
    # Offline later: the cached copy is still the newest.
    assert cr.newest_data(cache, None).where == "a cached release"
    missing = urllib.error.HTTPError(cr.LATEST_DATA_URL, 404, "Not Found", {}, io.BytesIO())
    os.remove(cache)
    source = cr.newest_data(cache, _Opener(data=missing))
    assert source.where == "this Certo version"
    assert source.note == "the latest release has no model data yet"


def _refresh(args, opener=None):
    out = io.StringIO()
    code = refresh_main(
        build_parser().parse_args(["refresh", *args]), prompter=Prompter(out=out), opener=opener
    )
    return code, out.getvalue()


def test_refresh_writes_the_ratings_and_shows_them_with_prices(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    prices = {"claude-haiku-5-5": {"input_cost_per_token": 1e-7, "output_cost_per_token": 5e-7}}
    opener = _Opener(data=OSError("offline"), prices=prices)
    try:
        code, out = _refresh([], opener)
        assert code == 0
        assert "Model data of 2026-11-16, from this Certo version" in out
        assert "Prices: LiteLLM's current list." in out
        assert "claude-haiku-5-5" in out and "$0.1/$0.5" in out
        assert "flint-40b-local" in out and "(no data)" in out
        assert "Which models fit each kind of task" in out
        computed = cr.read_computed()
        assert computed["claude-haiku-5-5"].ratings["speed"] == 4.0
        assert computed["flint-40b-local"].ratings == {"cost": 5.0, "speed": 2.0}
        # Again, offline: what moved is measured from the last refresh.
        code, out = _refresh(["--offline"])
        assert code == 0 and "since the last refresh: none." in out
        assert "Prices: the installed LiteLLM's (offline)." in out
    finally:
        if os.path.exists(cr.ratings_path()):
            os.remove(cr.ratings_path())
