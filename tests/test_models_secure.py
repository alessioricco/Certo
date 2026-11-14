"""models_secure.py and `certo models secure`: keys move from models.yaml
to the settings file, named as ${NAME}; no key is ever printed."""

from __future__ import annotations

import io
import os
import stat

import pytest
import yaml

from certo.init_cmd import Prompter
from certo.models_cmd import models_main
from certo.models_secure import Move, plan_moves, rebuild_models_yaml, rewrite_models_yaml

_IDS = {
    "luna": "openai/gpt-6-luna",
    "sol": "openai/gpt-6.1-sol",
    "haiku": "anthropic/claude-haiku-5-5",
    "qwen": "ollama/qwen3.8:27b",
    "odd": "someprovider/model-x",
}


def test_each_written_out_key_gets_the_providers_usual_name():
    entries = [
        {"name": "luna", "api_key": "sk-open"},
        {"name": "sol", "api_key": "sk-open"},
        {"name": "haiku", "api_key": "sk-ant"},
        {"name": "qwen", "base_url": "http://box:11434"},
        {"name": "odd", "api_key": "${ALREADY}"},
    ]

    moves = plan_moves(entries, _IDS, settings={}, environ={})

    assert [(m.model_name, m.variable, m.already_set) for m in moves] == [
        ("luna", "OPENAI_API_KEY", False),
        ("sol", "OPENAI_API_KEY", False),
        ("haiku", "ANTHROPIC_API_KEY", False),
    ]


def test_a_variable_holding_another_key_is_not_reused():
    entries = [{"name": "luna", "api_key": "sk-new"}, {"name": "sol", "api_key": "sk-other"}]

    moves = plan_moves(entries, _IDS, settings={"OPENAI_API_KEY": "sk-old"}, environ={})

    assert [m.variable for m in moves] == ["CERTO_LUNA_API_KEY", "CERTO_SOL_API_KEY"]


def test_the_environment_wins_over_the_settings_file_so_it_counts_too():
    moves = plan_moves(
        [{"name": "luna", "api_key": "sk-new"}],
        _IDS,
        settings={},
        environ={"OPENAI_API_KEY": "sk-shell"},
    )

    assert moves[0].variable == "CERTO_LUNA_API_KEY"


def test_the_same_key_already_in_the_settings_file_is_only_named():
    moves = plan_moves(
        [{"name": "haiku", "api_key": "sk-ant"}],
        _IDS,
        settings={"ANTHROPIC_API_KEY": "sk-ant"},
        environ={},
    )

    assert moves[0].already_set is True


def test_a_key_only_in_the_shell_is_still_written_to_the_file():
    moves = plan_moves(
        [{"name": "haiku", "api_key": "sk-ant"}],
        _IDS,
        settings={},
        environ={"ANTHROPIC_API_KEY": "sk-ant"},
    )

    assert (moves[0].variable, moves[0].already_set) == ("ANTHROPIC_API_KEY", False)


def test_an_unknown_provider_gets_a_name_from_its_prefix():
    moves = plan_moves([{"name": "odd", "api_key": "k"}], _IDS, settings={}, environ={})

    assert moves[0].variable == "SOMEPROVIDER_API_KEY"


def test_a_move_never_shows_its_key():
    assert "sk-secret" not in repr(Move("luna", "OPENAI_API_KEY", "sk-secret"))


_TEXT = """\
# My models. Keys were here.
models:
  # The cheap one
  - name: luna
    api_key: "sk-open"   # pasted in October
  - name: haiku
    api_key: sk-ant
    reasoning_effort: high
  - name: qwen
    base_url: http://box:11434
"""


def test_rewrite_keeps_comments_and_layout():
    moves = [
        Move("luna", "OPENAI_API_KEY", "sk-open"),
        Move("haiku", "ANTHROPIC_API_KEY", "sk-ant"),
    ]

    result = rewrite_models_yaml(_TEXT, moves)

    assert result == _TEXT.replace('"sk-open"', '"${OPENAI_API_KEY}"').replace(
        "api_key: sk-ant", 'api_key: "${ANTHROPIC_API_KEY}"'
    )
    assert "sk-" not in result


def test_a_one_line_entry_falls_back_to_rebuilding_the_file():
    text = "models:\n  - {name: luna, api_key: sk-open}\n"
    moves = [Move("luna", "OPENAI_API_KEY", "sk-open")]

    with pytest.raises(ValueError):
        rewrite_models_yaml(text, moves)
    result = rebuild_models_yaml(text, moves)

    assert yaml.safe_load(result) == {"models": [{"name": "luna", "api_key": "${OPENAI_API_KEY}"}]}
    assert "Comments of the old file were not kept" in result


# --- the command -----------------------------------------------------------


@pytest.fixture
def files(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CERTO_LUNA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config"
    (config / "certo").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    models = tmp_path / "models.yaml"
    models.write_text(_TEXT)
    listing = tmp_path / "models_list.yaml"
    listing.write_text(
        yaml.safe_dump(
            {"models": [{"name": n, "model": m, "ratings": {"code": 1}} for n, m in _IDS.items()]}
        )
    )
    monkeypatch.setenv("CERTO_MODELS_FILE", str(models))
    monkeypatch.setenv("CERTO_MODELS_LIST_FILE", str(listing))
    return models, config / "certo" / ".env"


def _run(argv, interactive=False):
    out = io.StringIO()
    code = models_main(argv, prompter=Prompter(out=out), interactive=interactive)
    return code, out.getvalue()


def test_secure_moves_the_keys_and_prints_none(files):
    models, settings = files

    code, output = _run(["secure", "--yes"])

    assert code == 0
    assert "sk-open" not in output and "sk-ant" not in output
    assert "OPENAI_API_KEY" in output and "ANTHROPIC_API_KEY" in output
    assert "sk-" not in models.read_text()
    assert "# pasted in October" in models.read_text()
    env = settings.read_text()
    assert "OPENAI_API_KEY='sk-open'" in env and "ANTHROPIC_API_KEY='sk-ant'" in env
    if os.name == "posix":
        assert stat.S_IMODE(settings.stat().st_mode) == 0o600
        assert stat.S_IMODE(models.stat().st_mode) == 0o600


def test_the_moved_keys_still_reach_the_models(files, monkeypatch):
    from certo.config import load_settings_files
    from certo.model_catalog import load_model_catalog

    models, settings = files
    _run(["secure", "--yes"])
    environ: dict[str, str] = {}
    load_settings_files(dotenv_path=os.devnull, user_path=str(settings), environ=environ)

    catalog = load_model_catalog(
        os.environ["CERTO_MODELS_LIST_FILE"], str(models), strict=False, environ=environ
    )

    keys = {m.name: m.api_key for m in catalog.models if m.configured}
    assert keys["luna"] == "sk-open" and keys["haiku"] == "sk-ant"
    assert catalog.load_warnings == ()


def test_without_a_terminal_or_yes_nothing_changes(files):
    models, settings = files

    code, output = _run(["secure"])

    assert code == 1
    assert models.read_text() == _TEXT
    assert not settings.exists()
    assert "--yes" in output


def test_nothing_to_move_says_so(files):
    models, _ = files
    models.write_text('models:\n  - name: luna\n    api_key: "${OPENAI_API_KEY}"\n')

    code, output = _run(["secure", "--yes"])

    assert code == 0
    assert "no key written out" in output
