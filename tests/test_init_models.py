"""`certo init models`, driven by a scripted terminal: no model and no
network (the model check and the Ollama listing are fakes)."""

from __future__ import annotations

import os

import pytest
import yaml
from test_init_cmd import Script

from certo import init_cmd
from certo.init_models import init_models_main
from certo.llm_check import LLMCheckResult

SECRET = "sk-test-SECRET-never-shown"
_INSTALLED = ["qwen3.8:27b", "gemma4:31b-it-qat", "qwen3.6:35b", "bonsai-2:27b"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty settings folder with the settings `certo init` writes for
    Ollama, and a project folder to run from."""
    config = tmp_path / "config"
    (config / "certo").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    settings = config / "certo" / ".env"
    settings.write_text(
        "CERTO_LLM_MODEL=ollama/qwen3.8:27b\nCERTO_LLM_BASE_URL=http://gpu-box:11434\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return config / "certo"


def _checks(failing=()):
    seen = []

    def check(cfg, **_kw):
        seen.append(cfg)
        ok = not any(name in cfg.model for name in failing)
        return LLMCheckResult(
            ok=ok,
            model=cfg.model,
            base_url=cfg.base_url,
            latency_seconds=0.5,
            error_kind=None if ok else "no_tool_call",
            error=None if ok else "no tool call",
        )

    return check, seen


def _run(answers, secrets=(), failing=(), installed=_INSTALLED):
    script = Script(answers=answers, secrets=secrets)
    check, seen = _checks(failing)
    code = init_models_main(
        [],
        prompter=script.prompter(),
        check=check,
        fetch_models=lambda _url: list(installed),
        interactive=True,
    )
    return code, script.text, seen


def _number(text: str, label: str) -> str:
    """The menu number in front of `label`."""
    for line in text.splitlines():
        if label in line and "." in line:
            return line.split(".", 1)[0].strip()
    raise AssertionError(f"{label!r} not in the menu:\n{text}")


def _menu(home) -> str:
    _code, text, _seen = _run([""])
    return text


def test_the_menu_starts_from_the_saved_model_and_offers_what_is_reachable(home):
    text = _menu(home)

    assert "  Your model\n   1. [x] qwen3.8-27b-local  already set up" in text
    assert "  On gpu-box:11434" in text
    assert "gemma4-31b-qat-local  reasoning 2 · precision 2 · code 2 · cost 5" in text
    # Not in the list: a name of its own, never one the list already uses
    # (qwen3.6-35b-local is qwen3.6:35b-a3b there).
    assert "qwen3.6-35b-local-2  not in Certo's list: you rate it" in text
    assert "DeepSeek models (asks for a key)" in text
    assert "Kimi (Moonshot AI) models (asks for a key)" in text
    assert "Another model (type any LiteLLM model id)" in text


def test_one_model_only_writes_nothing(home):
    code, text, seen = _run([""])

    assert code == 0
    assert "nothing was written" in text
    assert seen == []
    assert not (home / "models.yaml").exists()


def test_choosing_a_listed_model_tests_both_and_writes_the_files(home):
    menu = _menu(home)
    gemma = _number(menu, "gemma4-31b-qat-local ")

    code, text, seen = _run([gemma, "", ""])  # pick, done, mode: the default

    assert code == 0
    assert [c.model for c in seen] == ["ollama/qwen3.8:27b", "ollama/gemma4:31b-it-qat"]
    assert all(c.base_url == "http://gpu-box:11434" for c in seen)
    models = yaml.safe_load((home / "models.yaml").read_text())["models"]
    assert models == [
        {"name": "qwen3.8-27b-local", "base_url": "http://gpu-box:11434"},
        {"name": "gemma4-31b-qat-local", "base_url": "http://gpu-box:11434"},
    ]
    if os.name != "nt":  # Windows chmod cannot enforce Unix owner/group permissions.
        assert oct(os.stat(home / "models.yaml").st_mode & 0o777) == "0o600"
    assert (home / "models_list.yaml").exists()
    # The copy's origin, for certo models update.
    assert (home / ".models_list.base.yaml").read_text() == (home / "models_list.yaml").read_text()
    assert (home / "task_profiles.yaml").exists()
    assert "What --auto-model would choose:" in text
    assert "How --escalate would climb:" in text
    # One model stays the default mode.
    assert "  1. Just one model, without --auto-model or --escalate" in text
    assert "CERTO_MODEL_SELECTION=manual" in (home / ".env").read_text()


def test_a_model_that_fails_the_test_is_left_out(home):
    menu = _menu(home)
    picks = f"{_number(menu, 'gemma4-31b-qat-local ')}"

    code, text, _seen = _run([picks, ""], failing=("gemma4",))

    assert code == 1
    assert "  no  gemma4-31b-qat-local:" in text
    assert "Fewer than two models passed the test, so nothing was written." in text
    assert not (home / "models.yaml").exists()


class LiveScript(Script):
    """A Script whose answers may be functions of the screen so far, for
    menus whose numbers are known only once they are shown."""

    def _input(self, prompt):
        answer = super()._input(prompt)
        return answer(self.text) if callable(answer) else answer


def _last_menu(text: str) -> str:
    return text.rsplit("Numbers to add", 2)[-2]


def test_a_key_for_another_provider_goes_only_to_the_settings_file(home):
    deepseek = _number(_menu(home), "DeepSeek models (asks for a key)")
    script = LiveScript(
        answers=[deepseek, lambda text: _number(_last_menu(text), "deepseek-flash "), "", ""],
        secrets=[SECRET],
    )
    check, seen = _checks()

    code = init_models_main(
        [],
        prompter=script.prompter(),
        check=check,
        fetch_models=lambda _url: list(_INSTALLED),
        interactive=True,
    )

    assert code == 0
    assert SECRET not in script.text
    # The test call used the key typed, read back from the variable.
    assert [c.api_key for c in seen if c.model == "deepseek/deepseek-flash"] == [SECRET]
    assert f"DEEPSEEK_API_KEY='{SECRET}'" in (home / ".env").read_text()
    models = (home / "models.yaml").read_text()
    assert SECRET not in models
    assert "api_key: ${DEEPSEEK_API_KEY}" in models


def test_a_model_not_in_the_list_is_rated_by_the_user_next_to_listed_ones(home):
    menu = _menu(home)
    gemma = _number(menu, "gemma4-31b-qat-local ")
    bonsai = _number(menu, "bonsai-2-27b-local ")

    code, text, _seen = _run([f"{gemma} {bonsai}", "", "2", "", "3", "5", ""])

    assert code == 0
    assert "For comparison, Certo's list rates:" in text
    assert "  gemma4-31b-qat-local: reasoning 2 · precision 2 · code 2 · cost 5" in text
    listed = yaml.safe_load((home / "models_list.yaml").read_text())["models"]
    mine = next(m for m in listed if m["name"] == "bonsai-2-27b-local")
    assert mine["model"] == "ollama/bonsai-2:27b"
    assert mine["ratings"] == {"reasoning": 2, "precision": 3, "code": 3, "cost": 5}


def test_rating_zero_leaves_the_model_out(home):
    menu = _menu(home)
    bonsai = _number(menu, "bonsai-2-27b-local ")

    code, text, seen = _run([bonsai, "", "0"])

    assert code == 0
    assert "nothing was written" in text
    assert seen == []


def test_an_existing_models_yaml_is_kept_unless_the_user_says_replace(home):
    (home / "models.yaml").write_text("models:\n  - name: mine\n")
    menu = _menu(home)
    gemma = _number(menu, "gemma4-31b-qat-local ")

    code, text, _seen = _run([gemma, "", "n"])

    assert code == 0
    assert "Kept your models.yaml; nothing was written." in text
    assert (home / "models.yaml").read_text() == "models:\n  - name: mine\n"


def test_the_saved_cloud_key_is_reused_for_that_providers_models(home):
    (home / ".env").write_text(
        f"CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5\nCERTO_LLM_API_KEY='{SECRET}'\n"
    )
    text = _run([""], installed=[])[1]

    assert "  Your model\n   1. [x] claude-sonnet-5-5  already set up" in text
    assert "Anthropic (Claude) (CERTO_LLM_API_KEY found)" in text
    assert "claude-haiku-5-5" in text
    assert "Anthropic (Claude) models (asks for a key)" not in text
    assert SECRET not in text


def test_it_needs_a_terminal(home, capsys):
    assert init_models_main([], interactive=False) == 1
    assert "needs a terminal" in capsys.readouterr().err


def test_certo_init_models_is_the_subcommand(home, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "certo.init_models.init_models_main", lambda argv, **_kw: seen.append(argv) or 0
    )

    assert init_cmd.init_main(["models", "--timeout", "5"], interactive=True) == 0
    assert seen == [["--timeout", "5"]]
