"""`certo init` and `certo check` (init_cmd.py), plus the tool-calling check
and its plain-language messages (llm_check.py).

No network and no real model: questions go through a scripted Prompter,
the Ollama model list is a fake function, and the model check is either
monkeypatched or sent to a local fake Ollama server.
"""

from __future__ import annotations

import io
import json
import logging
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar

from certo.config import Config
import pytest
from dotenv import dotenv_values
from openhands.sdk.llm.message import MessageToolCall

from certo import cli, init_cmd, llm_check
from certo.config import load_config
from certo.init_cmd import Prompter, init_main
from certo.llm_check import LLMCheckResult, explain

SECRET = "sk-test-SECRET-value-1234"


class Script:
    """A scripted terminal: answers in order, records every prompt."""

    def __init__(self, answers=(), secrets=()):
        self.answers = list(answers)
        self.secrets = list(secrets)
        self.prompts = []
        self.out = io.StringIO()

    def _input(self, prompt):
        self.prompts.append(prompt)
        self.out.write(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected question: {prompt!r}")
        return self.answers.pop(0)

    def _secret(self, prompt):
        self.prompts.append(prompt)
        self.out.write(prompt + "\n")  # getpass echoes nothing
        if not self.secrets:
            raise AssertionError(f"unexpected secret prompt: {prompt!r}")
        return self.secrets.pop(0)

    def prompter(self):
        return Prompter(input_fn=self._input, secret_fn=self._secret, out=self.out)

    @property
    def text(self):
        return self.out.getvalue()


def _ok(cfg, **_kw):
    return LLMCheckResult(ok=True, model=cfg.model, base_url=cfg.base_url, latency_seconds=0.1)


@pytest.fixture
def no_check(monkeypatch):
    """Fail the test if a model check is attempted."""
    monkeypatch.setattr(
        init_cmd, "check_tool_calling", lambda *a, **k: pytest.fail("no check expected")
    )


@pytest.fixture
def checks(monkeypatch):
    """Record model checks and pass them."""
    seen = []

    def fake(cfg, **kw):
        seen.append(cfg)
        return _ok(cfg)

    monkeypatch.setattr(init_cmd, "check_tool_calling", fake)
    return seen


def _run(
    tmp_path, monkeypatch, argv, script=None, *, env=None, interactive=True, models=None, local=True
):
    """Run init in tmp_path. Unless `local` is False or argv picks a scope
    itself, adds --local: most tests here are about FOLDER/.env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    script = script or Script()
    if local and not {"--global", "--local", "--yes", "-y"} & set(argv):
        argv = [*argv, "--local"]

    def fetch(_url):
        if isinstance(models, Exception):
            raise models
        return list(models or [])

    code = init_main(
        argv,
        prompter=script.prompter(),
        env=env or {},
        interactive=interactive,
        fetch_models=fetch,
    )
    return code, script


def _active(folder):
    """The uncommented settings of folder/.env, uninterpolated."""
    lines = (folder / ".env").read_text().splitlines()
    return [line for line in lines if line and not line.startswith("#")]


# --- the question flow -------------------------------------------------------


def test_interactive_anthropic_flow_writes_only_the_chosen_settings(tmp_path, monkeypatch, checks):
    script = Script(answers=["2", ""], secrets=[SECRET])

    code, script = _run(tmp_path, monkeypatch, ["my-certo"], script)

    assert code == 0
    assert script.prompts == [
        "Choice [1]: ",
        "Model [anthropic/claude-sonnet-5-5]: ",
        "API key (hidden): ",
    ]
    folder = tmp_path / "my-certo"
    assert _active(folder) == [
        "CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5",
        f"CERTO_LLM_API_KEY='{SECRET}'",
    ]
    assert dotenv_values(folder / ".env")["CERTO_LLM_API_KEY"] == SECRET
    assert "ok: reachable, tool calling works." in script.text
    assert "cd my-certo" in script.text
    assert checks[0].model == "anthropic/claude-sonnet-5-5"
    assert checks[0].api_key == SECRET


def test_provider_menu_lists_the_choices_in_order(tmp_path, monkeypatch, checks):
    _code, script = _run(tmp_path, monkeypatch, [], Script(answers=["", ""], secrets=[SECRET]))

    menu = script.text.split("Which model provider do you want to use?\n", 1)[1]
    assert menu.splitlines()[:7] == [
        "  1. OpenAI",
        "  2. Anthropic (Claude)",
        "  3. Google Gemini",
        "  4. DeepSeek",
        "  5. Kimi (Moonshot AI)",
        "  6. Ollama (local models, no API key)",
        "  7. Other (any LiteLLM model id)",
    ]


@pytest.mark.parametrize(
    ("choice", "model", "other_presets"),
    [
        ("1", "openai/gpt-6.1-sol", ["Anthropic (Claude)", "Google Gemini", "Ollama"]),
        ("2", "anthropic/claude-sonnet-5-5", ["OpenAI", "Google Gemini", "Ollama"]),
        ("3", "gemini/gemini-3.8-flash", ["OpenAI", "Anthropic (Claude)", "Ollama"]),
        ("4", "deepseek/deepseek-flash", ["OpenAI", "Kimi (Moonshot AI)", "Ollama"]),
        ("5", "moonshot/kimi-k2.7-code", ["OpenAI", "DeepSeek", "Ollama"]),
    ],
)
def test_cloud_provider_env(tmp_path, monkeypatch, checks, choice, model, other_presets):
    _run(tmp_path, monkeypatch, ["w"], Script(answers=[choice, ""], secrets=[SECRET]))

    text = (tmp_path / "w" / ".env").read_text()
    assert _active(tmp_path / "w") == [f"CERTO_LLM_MODEL={model}", f"CERTO_LLM_API_KEY='{SECRET}'"]
    for label in other_presets:
        assert f"# {label}" in text
    # The chosen provider's preset isn't repeated below.
    assert text.count(model) == 1
    # Every preset is two lines a user uncomments.
    assert "# CERTO_LLM_MODEL=ollama/qwen3.8:27b\n# CERTO_LLM_BASE_URL=http://localhost:11434" in (
        text
    )


def test_a_typed_model_without_prefix_gets_the_providers(tmp_path, monkeypatch, checks):
    _run(tmp_path, monkeypatch, ["w"], Script(answers=["2", "claude-haiku-5-5"], secrets=[SECRET]))

    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=anthropic/claude-haiku-5-5"


def test_ollama_lists_installed_models_and_preselects_a_coder(tmp_path, monkeypatch, checks):
    script = Script(answers=["6", "gpu-box:11434", ""])

    _run(tmp_path, monkeypatch, ["w"], script, models=["llama3.2:3b", "qwen3-coder:30b"])

    assert script.prompts == [
        "Choice [1]: ",
        "Ollama address [http://localhost:11434]: ",
        "Choice [2]: ",
    ]
    assert _active(tmp_path / "w") == [
        "CERTO_LLM_MODEL=ollama/qwen3-coder:30b",
        "CERTO_LLM_BASE_URL=http://gpu-box:11434",
        "CERTO_LLM_TIMEOUT_SECONDS=1200",
    ]
    assert "local model may take a minute" in script.text
    assert "Anthropic (Claude)" in (tmp_path / "w" / ".env").read_text()


def test_ollama_offers_another_model_by_name(tmp_path, monkeypatch, checks):
    # The installed list plus one line to type a model that isn't pulled yet.
    script = Script(answers=["6", "", "3", "qwen2.5-coder:7b", ""])

    _run(tmp_path, monkeypatch, ["w"], script, models=["llama3:latest", "qwen3-coder:30b"])

    assert "  3. Another model (type its name)" in script.text
    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=ollama/qwen2.5-coder:7b"


def test_ollama_preselects_the_recommended_model_over_a_coder(tmp_path, monkeypatch, checks):
    # qwen3.8:27b beat qwen3-coder:30b in the 0.1.18 local benchmark, so
    # when both are installed the recommended one is offered first.
    script = Script(answers=["6", "", ""])

    _run(tmp_path, monkeypatch, ["w"], script, models=["qwen3-coder:30b", "qwen3.8:27b"])

    assert script.prompts[-1] == "Choice [2]: "
    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=ollama/qwen3.8:27b"


def test_ollama_unreachable_says_so_and_still_writes(tmp_path, monkeypatch, no_check):
    script = Script(answers=["6", "", ""])

    _run(tmp_path, monkeypatch, ["w", "--no-check"], script, models=OSError("refused"))

    assert "Couldn't reach Ollama at http://localhost:11434" in script.text
    assert "OLLAMA_HOST=0.0.0.0" in script.text
    assert _active(tmp_path / "w") == [
        "CERTO_LLM_MODEL=ollama/qwen3.8:27b",
        "CERTO_LLM_BASE_URL=http://localhost:11434",
        "CERTO_LLM_TIMEOUT_SECONDS=1200",
    ]


def test_ollama_without_models_prints_the_pull_commands(tmp_path, monkeypatch, no_check):
    script = Script(answers=["6", "", ""])

    _run(tmp_path, monkeypatch, ["w", "--no-check"], script, models=[])

    assert "ollama pull qwen3.8:27b" in script.text
    assert "ollama pull qwen2.5-coder:7b" in script.text


def test_other_asks_for_any_litellm_id_and_optional_key_and_url(tmp_path, monkeypatch, checks):
    script = Script(answers=["7", "deepseek/deepseek-chat", ""], secrets=[SECRET])

    _run(tmp_path, monkeypatch, ["w"], script)

    assert _active(tmp_path / "w") == [
        "CERTO_LLM_MODEL=deepseek/deepseek-chat",
        f"CERTO_LLM_API_KEY='{SECRET}'",
    ]
    text = (tmp_path / "w" / ".env").read_text()
    for label in ("OpenAI", "Anthropic (Claude)", "Google Gemini", "Ollama"):
        assert f"# {label}" in text


def test_found_environment_key_preselects_its_provider_and_is_referenced(
    tmp_path, monkeypatch, checks
):
    script = Script(answers=["", "", ""])

    _run(tmp_path, monkeypatch, ["w"], script, env={"ANTHROPIC_API_KEY": SECRET})

    assert script.prompts == [
        "Choice [2]: ",
        "Model [anthropic/claude-sonnet-5-5]: ",
        "Found ANTHROPIC_API_KEY in your environment. Use it? [Y/n]: ",
    ]
    assert _active(tmp_path / "w")[1] == "CERTO_LLM_API_KEY=${ANTHROPIC_API_KEY}"
    assert SECRET not in (tmp_path / "w" / ".env").read_text()
    assert checks[0].api_key == SECRET


def test_declining_the_environment_key_asks_for_one(tmp_path, monkeypatch, checks):
    script = Script(answers=["", "", "n"], secrets=["sk-other"])

    _run(tmp_path, monkeypatch, ["w"], script, env={"OPENAI_API_KEY": SECRET})

    assert script.prompts[-1] == "API key (hidden): "
    assert _active(tmp_path / "w")[1] == "CERTO_LLM_API_KEY='sk-other'"


def test_no_key_entered_leaves_the_line_to_fill_and_skips_the_check(
    tmp_path, monkeypatch, no_check
):
    _code, script = _run(tmp_path, monkeypatch, ["w"], Script(answers=["1", ""], secrets=[""]))

    assert _active(tmp_path / "w")[1] == "CERTO_LLM_API_KEY="
    assert "platform.openai.com/api-keys" in (tmp_path / "w" / ".env").read_text()
    assert "No API key yet" in script.text
    assert "  certo check" in script.text


def test_flags_skip_their_questions(tmp_path, monkeypatch, checks):
    script = Script(secrets=[SECRET])

    _run(tmp_path, monkeypatch, ["w", "--provider", "gemini", "--model", "gemini-x"], script)

    assert script.prompts == ["API key (hidden): "]
    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=gemini/gemini-x"


def test_model_flag_alone_infers_the_provider(tmp_path, monkeypatch, no_check):
    _run(
        tmp_path,
        monkeypatch,
        ["w", "--model", "ollama/qwen2.5-coder:7b", "--base-url", "http://h:1", "--no-check"],
        interactive=False,
    )

    assert _active(tmp_path / "w") == [
        "CERTO_LLM_MODEL=ollama/qwen2.5-coder:7b",
        "CERTO_LLM_BASE_URL=http://h:1",
        "CERTO_LLM_TIMEOUT_SECONDS=1200",
    ]


def test_yes_accepts_every_default_without_asking(tmp_path, monkeypatch, checks):
    code, script = _run(tmp_path, monkeypatch, ["w", "--yes"], env={"GEMINI_API_KEY": SECRET})

    assert code == 0
    assert script.prompts == []
    assert _active_lines(_user_file(tmp_path)) == [
        "CERTO_LLM_MODEL=gemini/gemini-3.8-flash",
        "CERTO_LLM_API_KEY=${GEMINI_API_KEY}",
    ]
    assert not (tmp_path / "w" / ".env").exists()
    assert (tmp_path / "w" / "tasks" / "wordle.md").exists()


def test_yes_with_local_writes_the_folder_env(tmp_path, monkeypatch, checks):
    code, _ = _run(tmp_path, monkeypatch, ["w", "--yes", "--local"], env={"GEMINI_API_KEY": SECRET})

    assert code == 0
    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=gemini/gemini-3.8-flash"
    assert not _user_file(tmp_path).exists()


# --- where the settings are saved ---------------------------------------------


def _user_file(tmp_path):
    return tmp_path / "xdg" / "certo" / ".env"


def _active_lines(path):
    return [line for line in path.read_text().splitlines() if line and not line.startswith("#")]


def test_all_projects_writes_the_user_file_and_a_sample_folder_without_env(
    tmp_path, monkeypatch, checks
):
    script = Script(answers=["2", "", "", ""], secrets=[SECRET])

    code, script = _run(tmp_path, monkeypatch, ["w"], script, local=False)

    assert code == 0
    assert script.prompts == [
        "Choice [1]: ",
        "Model [anthropic/claude-sonnet-5-5]: ",
        "API key (hidden): ",
        "Choice [1]: ",
        "Create a folder with sample tasks to try? [Y/n]: ",
    ]
    assert "Save these settings for:\n  1. All projects on this computer (recommended)\n" \
        "  2. This folder only\n" in script.text  # fmt: skip
    user = _user_file(tmp_path)
    if os.name != "nt":  # Windows chmod does not set Unix owner/group permissions.
        assert stat.S_IMODE(os.stat(user).st_mode) == 0o600
    assert dotenv_values(user)["CERTO_LLM_API_KEY"] == SECRET
    folder = tmp_path / "w"
    assert sorted(p.name for p in folder.iterdir()) == [".gitignore", "README.md", "tasks"]
    readme = (folder / "README.md").read_text()
    assert str(user) in readme
    assert "SETTINGS_FILE" not in readme
    assert f"Saved your settings for all projects in {user}" in script.text
    assert "  .env " not in script.text
    assert "cd w\n" in script.text
    assert 'certo "<task>" in any project folder' in script.text
    assert SECRET not in script.text


def test_all_projects_without_samples_creates_no_folder(tmp_path, monkeypatch, checks):
    script = Script(answers=["2", "", "1", "n"], secrets=[SECRET])

    code, script = _run(tmp_path, monkeypatch, ["w"], script, local=False)

    assert code == 0
    assert _user_file(tmp_path).exists()
    assert not (tmp_path / "w").exists()
    next_steps = script.text.split("Next:", 1)[1]
    assert "cd w" not in next_steps
    assert "wordle" not in next_steps
    assert 'You can now run certo "<task>" in any project folder' in next_steps


def test_this_folder_only_is_todays_behaviour(tmp_path, monkeypatch, checks):
    script = Script(answers=["2", "", "2"], secrets=[SECRET])

    code, script = _run(tmp_path, monkeypatch, ["w"], script, local=False)

    assert code == 0
    assert _active(tmp_path / "w")[0] == "CERTO_LLM_MODEL=anthropic/claude-sonnet-5-5"
    assert not _user_file(tmp_path).exists()
    assert "sample tasks to try? [Y/n]" not in script.text
    assert "any project folder" not in script.text


def _existing_user_file(tmp_path):
    user = _user_file(tmp_path)
    user.parent.mkdir(parents=True)
    user.write_text(f"CERTO_LLM_MODEL=openai/old-model\nCERTO_LLM_API_KEY={SECRET}\n")
    return user


def test_an_existing_user_file_is_shown_without_its_key_and_kept_on_no(
    tmp_path, monkeypatch, no_check
):
    user = _existing_user_file(tmp_path)
    before = user.read_text()
    script = Script(answers=["3", "", "1", "n", "n"], secrets=["other-key"])

    code, script = _run(tmp_path, monkeypatch, ["w"], script, local=False)

    assert code == 0
    assert "OpenAI, model openai/old-model" in script.text
    assert "Replace them? [Y/n]: " in script.prompts
    assert SECRET not in script.text
    assert user.read_text() == before
    assert "your new answers were not saved" in script.text


def test_an_existing_user_file_is_replaced_on_yes(tmp_path, monkeypatch, checks):
    user = _existing_user_file(tmp_path)
    script = Script(answers=["3", "", "1", "y", "n"], secrets=["other-key"])

    code, _ = _run(tmp_path, monkeypatch, ["w"], script, local=False)

    assert code == 0
    assert _active_lines(user)[0] == "CERTO_LLM_MODEL=gemini/gemini-3.8-flash"
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(user).st_mode) == 0o600


def test_without_asking_an_existing_user_file_needs_force(tmp_path, monkeypatch, no_check, capsys):
    user = _existing_user_file(tmp_path)
    before = user.read_text()

    code, _ = _run(tmp_path, monkeypatch, ["w", "--yes", "--no-check"], interactive=False)

    err = capsys.readouterr().err
    assert code == 1
    assert "openai/old-model" in err
    assert "--force" in err
    assert SECRET not in err
    assert user.read_text() == before
    assert not (tmp_path / "w").exists()

    code, _ = _run(
        tmp_path, monkeypatch, ["w", "--yes", "--no-check", "--force"], interactive=False
    )
    assert code == 0
    assert user.read_text() != before


def test_global_with_a_used_sample_folder_saves_settings_and_skips_samples(
    tmp_path, monkeypatch, no_check
):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "notes.txt").write_text("mine")

    code, script = _run(
        tmp_path, monkeypatch, ["w", "--global", "--provider", "ollama", "--no-check"],
        interactive=False,
    )  # fmt: skip

    assert code == 0
    assert _active_lines(_user_file(tmp_path))[0] == "CERTO_LLM_MODEL=ollama/qwen3.8:27b"
    # Live 2026-10-22: with the default 300 seconds, qwen3.8:27b's slow
    # answers timed out and restarted.
    assert "CERTO_LLM_TIMEOUT_SECONDS=1200" in _active_lines(_user_file(tmp_path))
    assert sorted(os.listdir(tmp_path / "w")) == ["notes.txt"]
    assert "Skipped the sample folder" in script.text


def test_choosing_this_folder_for_a_used_folder_is_refused(tmp_path, monkeypatch, no_check, capsys):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "notes.txt").write_text("mine")
    script = Script(answers=["6", "", "", "2"], secrets=[])

    code, _ = _run(tmp_path, monkeypatch, ["w"], script, local=False, models=OSError("down"))

    assert code == 1
    assert "not empty" in capsys.readouterr().err
    assert sorted(os.listdir(tmp_path / "w")) == ["notes.txt"]
    assert not _user_file(tmp_path).exists()


def test_no_terminal_without_flags_still_writes_the_folder_env(tmp_path, monkeypatch, no_check):
    code, _ = _run(tmp_path, monkeypatch, ["w"], interactive=False, local=False)

    assert code == 0
    assert (tmp_path / "w" / ".env").exists()
    assert not _user_file(tmp_path).exists()


def test_ctrl_c_at_the_scope_question_writes_nothing(tmp_path, monkeypatch, no_check):
    script = Script(answers=["2", ""], secrets=[SECRET])  # runs out at the scope question

    def stop(prompt):
        if script.answers:
            return script._input(prompt)
        raise EOFError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    code = init_main(
        ["w"],
        prompter=Prompter(input_fn=stop, secret_fn=script._secret, out=script.out),
        env={},
        interactive=True,
    )

    assert code == 130
    assert not (tmp_path / "w").exists()
    assert not _user_file(tmp_path).exists()


def test_ctrl_c_during_questions_writes_nothing(tmp_path, monkeypatch, no_check):
    def interrupted(_prompt):
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    out = io.StringIO()
    code = init_main(
        ["w"], prompter=Prompter(input_fn=interrupted, out=out), env={}, interactive=True
    )

    assert code == 130
    assert "Nothing was written" in out.getvalue()
    assert not (tmp_path / "w").exists()


def test_invalid_choice_is_asked_again(tmp_path, monkeypatch, checks):
    script = Script(answers=["9", "x", "1", ""], secrets=[SECRET])

    _run(tmp_path, monkeypatch, ["w"], script)

    assert script.text.count("Please enter a number from 1 to 7.") == 2


# --- the sample task at the end ---------------------------------------------------


def _with_sample(tmp_path, monkeypatch, answers, *, models=None):
    ran = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    script = Script(answers=answers, secrets=[SECRET])
    code = init_main(
        ["w", "--local"],
        prompter=script.prompter(),
        env={},
        interactive=True,
        fetch_models=lambda _url: list(models or []),
        run_sample=lambda folder, sample: ran.append((folder, sample.project)) or 0,
    )
    return code, script.text, ran


def test_after_a_passing_check_init_offers_to_run_the_sample(tmp_path, monkeypatch, checks):
    code, text, ran = _with_sample(tmp_path, monkeypatch, ["2", "", "1"])

    assert code == 0
    assert (
        f"It is built in {os.path.join('w', 'projects')}/<name>/.\nEach takes a few minutes."
        in text
    )
    assert "A run uses your model credits; Certo prints the cost at the end." in text
    assert "How good the result is depends on your model" in text
    assert ran == [("w", "wordle")]
    assert "certo tasks/wordle.md --project wordle" not in text  # it already ran
    assert "open projects/wordle/ to see what the agent built" in text


def test_the_menu_offers_every_sample(tmp_path, monkeypatch, checks):
    monkeypatch.setattr(init_cmd.shutil, "which", lambda name: f"/usr/bin/{name}")
    code, text, ran = _with_sample(tmp_path, monkeypatch, ["2", "", "4"])

    assert code == 0
    for sample in init_cmd.SAMPLES:
        assert sample.label in text
        assert (tmp_path / "w" / "tasks" / sample.file).exists()
    assert ran == [("w", "mazeman")]
    assert "open projects/mazeman/ to see what the agent built" in text
    # Every task `init` copies is in the menu.
    copied = {p.name for p in (tmp_path / "w" / "tasks").iterdir()}
    assert copied == {sample.file for sample in init_cmd.SAMPLES}


def test_without_node_the_browser_games_are_not_offered(tmp_path, monkeypatch, checks):
    monkeypatch.setattr(init_cmd.shutil, "which", lambda _name: None)
    _code, text, ran = _with_sample(tmp_path, monkeypatch, ["2", "", "3"])

    assert "Space rocks" not in text.split("Which one?")[1]
    assert "  3. Not now" in text
    assert ran == []


def test_not_now_keeps_the_next_steps(tmp_path, monkeypatch, checks):
    code, text, ran = _with_sample(tmp_path, monkeypatch, ["2", "", str(len(init_cmd.SAMPLES) + 1)])

    assert code == 0
    assert ran == []
    assert "certo tasks/wordle.md --project wordle" in text
    # And how to build a project of your own.
    assert '  certo "A command-line to-do list in Python, with tests" --project todo' in text
    assert "Each project lands in projects/<name>/" in text


def test_a_local_model_is_said_to_be_free_and_slower(tmp_path, monkeypatch, checks):
    _code, text, _ran = _with_sample(
        tmp_path, monkeypatch, ["6", "", "", str(len(init_cmd.SAMPLES) + 1)], models=["qwen3.8:27b"]
    )

    assert (
        "A sample takes 10 to 40 minutes: Wordle and space rocks the least, mazeman the most."
    ) in text
    assert "A run is free on your local model." in text


def test_no_sample_offer_when_the_check_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        init_cmd, "check_tool_calling", lambda cfg, **_k: _result("authentication", "bad key")
    )
    _code, text, ran = _with_sample(tmp_path, monkeypatch, ["2", ""])

    assert "Which one?" not in text
    assert ran == []


def test_the_sample_runs_as_a_normal_certo_run(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, cwd, check):
        seen.update(command=command, cwd=cwd)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(init_cmd.subprocess, "run", fake_run)

    assert init_cmd.run_sample_task(str(tmp_path)) == 0
    assert seen["command"][1:] == ["-m", "certo", "tasks/wordle.md", "--project", "wordle"]
    hanoi = init_cmd.SAMPLES[1]
    assert init_cmd.run_sample_task(str(tmp_path), hanoi) == 0
    assert seen["command"][1:] == ["-m", "certo", "tasks/hanoi.md", "--project", "hanoi"]
    assert seen["cwd"] == str(tmp_path)


# --- no terminal ---------------------------------------------------------------


def test_no_terminal_asks_nothing_and_comments_out_every_preset(tmp_path, monkeypatch, no_check):
    code, script = _run(tmp_path, monkeypatch, ["w"], interactive=False)

    assert code == 0
    assert script.prompts == []
    assert _active(tmp_path / "w") == []
    text = (tmp_path / "w" / ".env").read_text()
    for model in ("openai/", "anthropic/", "gemini/", "ollama/"):
        assert f"# CERTO_LLM_MODEL={model}" in text
    assert "No terminal, so nothing was asked" in script.text


def test_no_terminal_other_without_model_is_an_error(tmp_path, monkeypatch, no_check, capsys):
    code, _script = _run(tmp_path, monkeypatch, ["w", "--provider", "other"], interactive=False)

    assert code == 1
    assert "--provider other needs --model" in capsys.readouterr().err
    assert not (tmp_path / "w").exists()


# --- files and overwrite protection --------------------------------------------


def test_creates_the_workspace_files(tmp_path, monkeypatch, no_check):
    _run(tmp_path, monkeypatch, [], interactive=False)

    folder = tmp_path / "certo-workspace"
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(folder / ".env").st_mode) == 0o600
    assert (folder / ".gitignore").read_text().splitlines()[1:] == [
        ".env",
        "# What Certo builds and records.",
        "projects/",
        "artifacts/",
    ]
    assert sorted(p.name for p in (folder / "tasks").iterdir()) == [
        "hanoi.md",
        "invaders.md",
        "mazeman.md",
        "space-rocks.md",
        "wordle.md",
    ]
    readme = (folder / "README.md").read_text()
    assert readme.startswith(init_cmd.README_TITLE)
    for needle in ("certo check", "certo verify", "cost", "OLLAMA_CONTEXT_LENGTH", "projects/"):
        assert needle in readme


def test_existing_non_empty_folder_is_refused(tmp_path, monkeypatch, no_check, capsys):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "notes.txt").write_text("mine")

    code, _ = _run(tmp_path, monkeypatch, ["w"], interactive=False)

    assert code == 1
    assert "not empty" in capsys.readouterr().err
    assert sorted(os.listdir(tmp_path / "w")) == ["notes.txt"]


def test_existing_env_is_refused_before_any_question(tmp_path, monkeypatch, no_check, capsys):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / ".env").write_text("CERTO_LLM_MODEL=mine\n")

    code, script = _run(tmp_path, monkeypatch, ["w"])

    assert code == 1
    assert script.prompts == []
    assert "--force" in capsys.readouterr().err
    assert (tmp_path / "w" / ".env").read_text() == "CERTO_LLM_MODEL=mine\n"


def test_empty_existing_folder_is_fine(tmp_path, monkeypatch, no_check):
    (tmp_path / "w").mkdir()

    code, _ = _run(tmp_path, monkeypatch, ["w"], interactive=False)

    assert code == 0


def test_force_replaces_env_but_keeps_a_foreign_readme_and_merges_gitignore(
    tmp_path, monkeypatch, no_check
):
    folder = tmp_path / "w"
    folder.mkdir()
    (folder / ".env").write_text("OLD=1\n")
    (folder / "README.md").write_text("# My project\n")
    (folder / ".gitignore").write_text("node_modules/\n.env\n")

    code, script = _run(tmp_path, monkeypatch, ["w", "--force"], interactive=False)

    assert code == 0
    assert "OLD=1" not in (folder / ".env").read_text()
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(folder / ".env").st_mode) == 0o600
    assert (folder / "README.md").read_text() == "# My project\n"
    assert "Kept your existing README.md" in script.text
    assert (folder / ".gitignore").read_text() == "node_modules/\n.env\nprojects/\nartifacts/\n"


def test_force_refreshes_a_readme_init_wrote(tmp_path, monkeypatch, no_check):
    _run(tmp_path, monkeypatch, ["w"], interactive=False)
    (tmp_path / "w" / "README.md").write_text(init_cmd.README_TITLE + "\nold\n")

    _run(tmp_path, monkeypatch, ["w", "--force"], interactive=False)

    assert "certo check" in (tmp_path / "w" / "README.md").read_text()


def test_missing_node_is_mentioned(tmp_path, monkeypatch, no_check):
    monkeypatch.setattr(init_cmd.shutil, "which", lambda _name: None)

    _code, script = _run(tmp_path, monkeypatch, ["w"], interactive=False)

    assert "The browser games (space-rocks, mazeman, invaders) need Node 18" in script.text
    assert (tmp_path / "w" / "tasks" / "space-rocks.md").exists()


# --- the key never leaks -------------------------------------------------------


def test_key_never_appears_in_output_or_logs(tmp_path, monkeypatch, caplog, capsys):
    def failing_check(cfg, **_kw):
        logging.getLogger("certo").debug("checking %s", cfg.model)
        return llm_check._failure(cfg, RuntimeError(f"denied for key {SECRET}"), 0.0)

    monkeypatch.setattr(init_cmd, "check_tool_calling", failing_check)
    caplog.set_level(logging.DEBUG)
    script = Script(answers=["2", ""], secrets=[SECRET])

    code, script = _run(tmp_path, monkeypatch, ["w"], script)

    captured = capsys.readouterr()
    assert code == 0
    assert SECRET not in script.text
    assert SECRET not in captured.out + captured.err
    assert SECRET not in caplog.text
    assert "***" in script.text  # scrubbed, not dropped
    assert SECRET not in repr(init_cmd.Settings(init_cmd.load_providers()[0], "m", api_key=SECRET))


# --- the model check -----------------------------------------------------------


def test_failed_check_keeps_the_files_and_points_to_certo_check(tmp_path, monkeypatch):
    def bad_key(cfg, **_kw):
        return LLMCheckResult(
            ok=False, model=cfg.model, base_url=None, latency_seconds=0.1,
            error_kind="authentication", error="AuthenticationError: invalid x-api-key",
        )  # fmt: skip

    monkeypatch.setattr(init_cmd, "check_tool_calling", bad_key)

    _code, script = _run(tmp_path, monkeypatch, ["w"], Script(answers=["2", ""], secrets=[SECRET]))

    assert "Anthropic rejected the API key" in script.text
    assert "then run certo check in that folder" in script.text
    assert (tmp_path / "w" / ".env").exists()
    assert "  certo check" in script.text


def test_no_check_flag_skips_the_call(tmp_path, monkeypatch, no_check):
    code, _ = _run(
        tmp_path, monkeypatch, ["w", "--no-check"], Script(answers=["2", ""], secrets=[SECRET])
    )

    assert code == 0


def _result(kind=None, error="", model="anthropic/claude-sonnet-5-5", base_url=None):
    return LLMCheckResult(
        ok=False, model=model, base_url=base_url, latency_seconds=0.1,
        error_kind=kind, error=error,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_result("authentication", "invalid x-api-key"), "Anthropic rejected the API key"),
        (_result("rate_limit", "429"), "out of credit, or it is being rate limited"),
        (
            _result("bad_request", "Your credit balance is too low to access the API"),
            "out of credit",
        ),
        (_result("bad_request", "insufficient_quota"), "out of credit"),
        (
            _result("model_not_found", "NotFoundError: model: claude-x"),
            "doesn't know the model anthropic/claude-sonnet-5-5",
        ),
        (
            _result(
                "unavailable",
                'model "qwen3-coder:30b" not found, try pulling it first',
                model="ollama/qwen3-coder:30b",
                base_url="http://h:11434",
            ),
            "ollama pull qwen3-coder:30b",
        ),
        (
            _result("unavailable", "Connection refused", base_url="http://h:11434"),
            "Couldn't reach the server at http://h:11434",
        ),
        (_result("timeout", "timed out"), "Couldn't reach Anthropic"),
        (
            _result("bad_request", "registry.ollama.ai/library/llama2 does not support tools"),
            "doesn't support tool calling",
        ),
        (_result("no_tool_call", "no tool call"), "answered, but without calling a tool"),
        (_result("setup", "context window too small"), "can't use this model"),
        (_result("error", "boom"), "The check failed: boom"),
    ],
)
def test_explain_names_the_problem_and_the_fix(result, expected):
    assert expected in explain(result, "Anthropic")


def test_explain_ok():
    ok = LLMCheckResult(ok=True, model="m", base_url=None, latency_seconds=0.1)
    assert explain(ok) == "ok: reachable, tool calling works."


def _tool_response(calls):
    return SimpleNamespace(
        message=SimpleNamespace(tool_calls=calls),
        metrics=SimpleNamespace(accumulated_token_usage=None, accumulated_cost=0.0),
    )


@pytest.mark.parametrize(("calls", "ok"), [(None, False), ([], False), (["call"], True)])
def test_check_tool_calling_passes_only_on_a_tool_call(monkeypatch, calls, ok):
    sent = {}
    if calls:
        calls = [MessageToolCall(id="1", name="finish", arguments="{}", origin="completion")]

    class FakeLLM:
        def model_copy(self, *, update):
            sent["update"] = update
            return self

    def fake_completion(llm, messages, tools):
        sent["tools"] = [t.name for t in tools]
        return _tool_response(calls)

    monkeypatch.setattr(llm_check, "build_llm", lambda cfg, usage_id: FakeLLM())
    monkeypatch.setattr(llm_check, "make_llm_completion", fake_completion)

    result = llm_check.check_tool_calling(
        load_config({"CERTO_LLM_MODEL": "x/y", "CERTO_LLM_API_KEY": "k"})
    )

    assert result.ok is ok
    assert sent["tools"] == ["finish"]
    assert sent["update"]["num_retries"] == 0
    assert result.error_kind == (None if ok else "no_tool_call")


class _FakeOllama(BaseHTTPRequestHandler):
    """LiteLLM's `ollama/` route posts to /api/generate with the tools in the
    prompt and parses a JSON function call out of the reply."""

    mode: ClassVar[str] = "tool"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        model = body.get("model")
        if self.path == "/api/show":
            return self._send(200, {"model_info": {"general.architecture": "qwen3"}})
        if self.mode == "missing":
            return self._send(404, {"error": f'model "{model}" not found, try pulling it first'})
        if self.mode == "notools":
            return self._send(
                400, {"error": f"registry.ollama.ai/library/{model} does not support tools"}
            )
        reply = (
            json.dumps({"name": "finish", "arguments": {"message": "OK"}})
            if self.mode == "tool"
            else "OK"
        )
        done = {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}
        return self._send(
            200, {"model": model, "created_at": "2026-01-01T00:00:00Z", "response": reply, **done}
        )

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("tool", "ok: reachable, tool calling works."),
        ("text", "answered, but without calling a tool"),
        ("missing", "Ollama has no model named qwen3-coder:30b"),
        ("notools", "doesn't support tool calling"),
    ],
)
def test_tool_check_through_the_sdk_against_a_fake_ollama(fake_ollama, monkeypatch, mode, expected):
    # The real SDK + LiteLLM request path, against a local server.
    monkeypatch.setattr(_FakeOllama, "mode", mode)
    cfg = load_config(
        {"CERTO_LLM_MODEL": "ollama/qwen3-coder:30b", "CERTO_LLM_BASE_URL": fake_ollama}
    )

    result = llm_check.check_tool_calling(cfg, timeout=10)

    assert expected in explain(result, "Ollama")


def test_tool_check_reports_an_unreachable_server():
    cfg = load_config(
        {"CERTO_LLM_MODEL": "ollama/qwen3-coder:30b", "CERTO_LLM_BASE_URL": "http://127.0.0.1:9"}
    )

    result = llm_check.check_tool_calling(cfg, timeout=10)

    assert "Couldn't reach the server at http://127.0.0.1:9" in explain(result, "Ollama")


# --- certo check -------------------------------------------------------------


def test_certo_check_without_settings_lists_the_three_places(tmp_path, monkeypatch, no_check):
    monkeypatch.chdir(tmp_path)
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 1
    text = out.getvalue()
    assert "CERTO_LLM_MODEL             not set" in text
    assert "export CERTO_LLM_MODEL=" in text
    assert str(tmp_path / ".env") in text
    assert init_cmd.user_settings_path() in text


def test_certo_check_shows_where_each_setting_comes_from(tmp_path, monkeypatch, checks):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CERTO_LLM_BASE_URL", "http://from-env")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    user = tmp_path / "xdg" / "certo" / ".env"
    user.parent.mkdir(parents=True)
    user.write_text(f"CERTO_LLM_MODEL=openai/from-user\nCERTO_LLM_API_KEY={SECRET}\n")
    (work / ".env").write_text("CERTO_LLM_MODEL=openai/from-folder\n")
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 0
    text = out.getvalue()
    assert f"CERTO_LLM_MODEL             openai/from-folder, from ./.env ({work / '.env'})" in text
    assert f"CERTO_LLM_API_KEY           set, from user settings ({user})" in text
    assert "CERTO_LLM_BASE_URL          http://from-env, from environment variable" in text
    assert "REASONING_EFFORT" not in text
    assert SECRET not in text
    assert text.index("Settings:") < text.index("Checking the model")
    assert checks[0].model == "openai/from-folder"
    assert checks[0].api_key == SECRET


def test_certo_check_says_not_set_for_a_missing_key(tmp_path, monkeypatch, no_check):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CERTO_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CERTO_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/x")
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 1
    assert "CERTO_LLM_API_KEY           not set" in out.getvalue()


def test_certo_check_reads_the_user_settings_file(tmp_path, monkeypatch, checks):
    monkeypatch.chdir(tmp_path)
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "certo").mkdir(parents=True)
    (tmp_path / "xdg" / "certo" / ".env").write_text(
        "CERTO_LLM_MODEL=gemini/u\nCERTO_LLM_API_KEY=k\n"
    )

    assert init_cmd.check_main([], out=io.StringIO()) == 0
    assert checks[0].model == "gemini/u"


def test_certo_check_reads_the_folders_env(tmp_path, monkeypatch, checks):
    monkeypatch.chdir(tmp_path)
    for name in ("CERTO_LLM_MODEL", "CERTO_LLM_API_KEY", "CERTO_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("CERTO_LLM_MODEL=gemini/g\nCERTO_LLM_API_KEY=k\n")
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 0
    assert checks[0].model == "gemini/g"
    assert "ok: reachable" in out.getvalue()


def test_certo_check_failure_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/x")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    monkeypatch.setattr(
        init_cmd,
        "check_tool_calling",
        lambda cfg, **_kw: _result("authentication", "bad", model=cfg.model),
    )
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 1
    assert "OpenAI rejected the API key" in out.getvalue()
    assert "then run: certo check" in out.getvalue()
    assert "CERTO_LLM_MODEL             openai/x, from environment variable" in out.getvalue()


# --- CLI dispatch --------------------------------------------------------------


def test_init_and_check_dispatch_only_on_the_exact_first_argument(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "init_main", lambda argv, **_kw: seen.append(("init", argv)) or 0)
    monkeypatch.setattr(cli, "check_main", lambda argv: seen.append(("check", argv)) or 0)

    assert cli.main(["init", "x", "--yes"]) == 0
    assert cli.main(["check"]) == 0
    assert seen == [("init", ["x", "--yes"]), ("check", [])]


@pytest.mark.parametrize("task", ["init a git repo here", "check the tests", "Init"])
def test_a_task_mentioning_init_or_check_is_still_a_task(monkeypatch, task):
    monkeypatch.setattr(cli, "init_main", lambda _argv, **_kw: pytest.fail("init must not run"))
    monkeypatch.setattr(cli, "check_main", lambda _argv: pytest.fail("check must not run"))
    # Reaching load_config means main() took the task path.
    monkeypatch.setattr(cli, "load_config", lambda: pytest.fail("task path"))

    with pytest.raises(pytest.fail.Exception, match="task path"):
        cli.main([task])


def test_load_dotenv_from_litellm_is_disabled():
    # LiteLLM's import-time load_dotenv() searched upward from its install
    # folder and could load a ~/.env (see certo/__init__.py).
    assert os.environ.get("LITELLM_MODE") == "PRODUCTION"


# --- certo check: the model catalog ---------------------------------------------------

_CATALOG = """
models:
  - name: qwen-local
    model: ollama/qwen3-coder:30b
    base_url: http://localhost:11434
    ratings: {reasoning: 2, code: 3, cost: 5}
  - name: gpt-luna
    model: openai/gpt-5.6-luna
    api_key: sk-CATALOG-SECRET
    ratings: {reasoning: 3, code: 4, cost: 4}
  - name: claude-sonnet
    model: anthropic/claude-sonnet-5-5
    api_key: sk-CATALOG-SECRET
    ratings: {reasoning: 5, code: 5, cost: 2}
  - name: gemma-local
    model: ollama/gemma4:31b
    base_url: http://localhost:11434
    ratings: {reasoning: 2, code: 2, cost: 5}
    activated: false
task_profiles:
  default:
    weights: {reasoning: 1, code: 1, cost: 1}
escalation:
  ladders:
    default:
      - model: qwen-local
      - model: gpt-luna
      - model: claude-sonnet
    local-only:
      - model: qwen-local
      - model: gemma-local
"""


def _check_with_catalog(tmp_path, monkeypatch, catalog, argv=()):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    from model_file_helpers import write_split_model_files

    # In the project folder: the lookup finds the files there.
    write_split_model_files(tmp_path, catalog)
    out = io.StringIO()
    code = init_cmd.check_main(list(argv), out=out)
    return code, out.getvalue()


def test_certo_check_reports_the_catalog(tmp_path, monkeypatch, checks):
    code, text = _check_with_catalog(tmp_path, monkeypatch, _CATALOG)

    assert code == 0
    assert "Active models: qwen-local, gpt-luna, claude-sonnet" in text
    assert "Inactive models: gemma-local" in text
    assert "Ladder 'default': qwen-local -> gpt-luna -> claude-sonnet" in text
    assert "Ladder 'local-only': qwen-local (1 rung(s) skipped)" in text
    assert (
        "Derived ladder: qwen-local (capability 5, cost rating 5; effort default) "
        "-> gpt-luna (capability 7, cost rating 4; effort default) "
        "-> claude-sonnet (capability 10, cost rating 2; effort default)"
    ) in text
    assert "Warning: Ladder 'local-only', rung 2: gemma-local has 'activated: false'" in text
    assert "sk-CATALOG-SECRET" not in text
    assert [c.model for c in checks] == ["openai/main"]  # no --models: only the main model


_PROFILES_CATALOG = _CATALOG.replace(
    """task_profiles:
  default:""",
    """task_profiles:
  debugging:
    triggers: [fix, bug]
    weights: {reasoning: 3, code: 1}
    model: gpt-luna
  scaffolding:
    triggers: [scaffold]
    weights: {cost: 2}
  default:""",
)


def _split_check(tmp_path, monkeypatch, argv):
    from model_file_helpers import write_split_model_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    write_split_model_files(tmp_path, _PROFILES_CATALOG)
    out = io.StringIO()
    code = init_cmd.check_main(list(argv), out=out)
    return code, out.getvalue()


def test_certo_check_shows_the_models_each_task_profile_would_use(tmp_path, monkeypatch, checks):
    code, text = _split_check(tmp_path, monkeypatch, [])

    assert code == 0
    assert "Task profiles (--auto-model), checked in this order:" in text
    assert "    debugging, title has: fix, bug\n" in text
    assert (
        "      gpt-luna (named by the profile, score 13), claude-sonnet (score 20), "
        "qwen-local (score 9)\n"
    ) in text
    assert "    scaffolding, title has: scaffold\n" in text
    assert "    default, when no other profile matches\n" in text
    assert "sk-CATALOG-SECRET" not in text


def test_certo_check_task_shows_the_route_and_calls_no_model(tmp_path, monkeypatch, checks):
    code, text = _split_check(tmp_path, monkeypatch, ["--task", "Fix the bugs in the parser"])

    assert code == 0
    assert checks == []
    assert "Task title: Fix the bugs in the parser" in text
    assert 'Profile: debugging ("fix" is in the title)' in text
    assert (
        "Models, in the order --auto-model tries them "
        "(the profile names gpt-luna; fallbacks ranked by weights):\n"
        "  1. gpt-luna (named by the profile, score 13)\n"
        "  2. claude-sonnet (score 20)\n"
        "  3. qwen-local (score 9)\n"
    ) in text
    assert "Active models" not in text  # only the route, not the whole report


def test_certo_check_task_reads_a_task_file_and_falls_back_to_default(
    tmp_path, monkeypatch, checks
):
    # The body says "fix", but only the title counts.
    (tmp_path / "task.md").write_text("# A Wordle game\n\nFix every bug you find.\n")
    code, text = _split_check(tmp_path, monkeypatch, ["--task", "task.md"])

    assert code == 0
    assert "Task title: A Wordle game" in text
    assert "Profile: default (no other profile's trigger word is in the title)" in text
    assert "  1. claude-sonnet (score 12)" in text


def test_certo_check_task_without_model_files_is_an_error(tmp_path, monkeypatch, checks):
    monkeypatch.chdir(tmp_path)
    out = io.StringIO()

    assert init_cmd.check_main(["--task", "Fix it"], out=out) == 1
    assert "Error: No models_list.yaml found" in out.getvalue()


def test_certo_check_names_the_models_left_out_of_the_derived_ladder(tmp_path, monkeypatch, checks):
    # gemma-local active: as cheap as qwen-local and weaker, so it isn't a rung.
    catalog = _CATALOG.replace("    activated: false\n", "")
    code, text = _check_with_catalog(tmp_path, monkeypatch, catalog)

    assert code == 0
    assert (
        "Derived ladder: qwen-local (capability 5, cost rating 5; effort default) -> gpt-luna"
        in text
    )
    assert (
        "Left out of the derived ladder: gemma-local "
        "(qwen-local is at least as capable and costs no more)"
    ) in text


def test_certo_check_exits_1_on_a_catalog_error(tmp_path, monkeypatch, checks):
    broken = _CATALOG.replace("      - model: gpt-luna\n", "      - model: gpt-lunaa\n")
    code, text = _check_with_catalog(tmp_path, monkeypatch, broken)

    assert code == 1
    assert "Error: Ladder 'default', rung 2: there is no model named 'gpt-lunaa'." in text


def test_certo_check_models_tests_every_active_model(tmp_path, monkeypatch):
    seen = []

    def fake(cfg, **_kw):
        seen.append(cfg)
        failed = cfg.model.startswith("anthropic/")
        return LLMCheckResult(
            ok=not failed,
            model=cfg.model,
            base_url=cfg.base_url,
            latency_seconds=0.1,
            error_kind="authentication" if failed else None,
            error="bad key" if failed else None,
        )

    monkeypatch.setattr(init_cmd, "check_tool_calling", fake)
    code, text = _check_with_catalog(tmp_path, monkeypatch, _CATALOG, ["--models"])

    assert code == 1
    assert [c.model for c in seen] == [
        "openai/main",
        "ollama/qwen3-coder:30b",
        "openai/gpt-5.6-luna",
        "anthropic/claude-sonnet-5-5",
    ]
    # Each entry's own settings, never .env's.
    assert seen[1].api_key is None and seen[1].base_url == "http://localhost:11434"
    assert "qwen-local (ollama/qwen3-coder:30b)... ok: reachable, tool calling works." in text
    assert "claude-sonnet (anthropic/claude-sonnet-5-5)... Anthropic rejected the API key." in text
    assert "Check its api_key in models.yaml" in text
    assert "sk-CATALOG-SECRET" not in text


def test_certo_check_models_without_a_catalog_is_an_error(tmp_path, monkeypatch, checks):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    out = io.StringIO()

    assert init_cmd.check_main(["--models"], out=out) == 1
    text = out.getvalue()
    assert "--models: No models.yaml found" in text
    assert "models.yaml.example" in text


def test_certo_check_without_a_catalog_prints_no_report(tmp_path, monkeypatch, checks):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 0
    assert "Model catalog" not in out.getvalue()


def test_certo_check_names_both_files_and_counts_unused_list_models(tmp_path, monkeypatch, checks):
    from pathlib import Path

    from model_file_helpers import write_split_model_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    models_path = write_split_model_files(tmp_path, _CATALOG)["models_path"]
    personal = Path(models_path)
    personal.write_text(
        "models:\n  - name: qwen-local\n  - name: gpt-luna\n    api_key: sk-x\n"
        "  - name: claude-sonnet\n    api_key: sk-x\n"
    )
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 0
    text = out.getvalue()
    assert f"List: {tmp_path / 'models_list.yaml'}" in text
    assert f"Personal settings: {tmp_path / 'models.yaml'}" in text
    assert "Active models: qwen-local, gpt-luna, claude-sonnet" in text
    assert "1 other model(s) in models_list.yaml, not used (not in models.yaml)" in text
    assert "gemma-local isn't in models.yaml, so this rung is skipped" in text


def test_certo_check_with_only_the_list_says_to_create_models_yaml(tmp_path, monkeypatch, checks):
    from pathlib import Path

    from model_file_helpers import write_split_model_files

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CERTO_LLM_MODEL", "openai/main")
    monkeypatch.setenv("CERTO_LLM_API_KEY", "k")
    models_path = write_split_model_files(tmp_path, _CATALOG)["models_path"]
    Path(models_path).unlink()
    out = io.StringIO()

    assert init_cmd.check_main([], out=out) == 1
    assert "Error: No models.yaml found" in out.getvalue()


@pytest.mark.parametrize(
    "result",
    [
        _result("authentication", "invalid x-api-key"),
        _result("model_not_found", "no such model"),
        _result("no_tool_call", "no tool call"),
        _result("unavailable", "Connection refused", base_url="http://h:11434"),
    ],
)
def test_explain_does_not_claim_the_setting_is_in_dot_env(result):
    # The value usually comes from the user settings file or the shell,
    # and certo check prints where; the message mustn't say ".env".
    text = explain(result, "Anthropic")
    assert ".env" not in text
    assert "in your settings" in text


# =============================================================================
# #35: run_check prints the Ollama version/window/tok-s header, and stays
# byte-identical for cloud models. check_tool_calling is monkeypatched: no
# network, no key.
# =============================================================================


def _run_check_cfg(**overrides) -> Config:
    """A Config for run_check tests. Named with a prefix so it never
    collides with a future generic _cfg in this file."""
    base = {
        "model": "openai/gpt-4o",
        "api_key": "sk-test",
        "base_url": None,
        "workspace": ".",
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


def _llm_result(**kwargs) -> LLMCheckResult:
    """An LLMCheckResult for run_check tests. Named _llm_result, not
    _result: this file already has a _result helper at ~line 843 with a
    different signature, and redefining it would break that one."""
    defaults = dict(ok=True, model="openai/gpt-4o", base_url=None, latency_seconds=1.2)
    defaults.update(kwargs)
    return LLMCheckResult(**defaults)


def _run_check(monkeypatch, cfg, result):
    """Run init_cmd.run_check with load_config and check_tool_calling mocked.
    Returns (ok, the text written to `out`)."""
    monkeypatch.setattr(init_cmd, "load_config", lambda env: cfg)
    monkeypatch.setattr(init_cmd, "check_tool_calling", lambda cfg, *, timeout: result)
    out = io.StringIO()
    ok = init_cmd.run_check(None, out)
    return ok, out.getvalue()


def test_run_check_cloud_output_is_byte_identical(monkeypatch):
    """If this fails, certo check gained a stray '1.2s' line for cloud
    models — the opposite of the issue's 'nothing changes for cloud models'."""
    ok, text = _run_check(
        monkeypatch,
        _run_check_cfg(model="openai/gpt-4o"),
        _llm_result(model="openai/gpt-4o", latency_seconds=1.2),
    )
    assert ok is True
    assert text.count("\n") == 1
    assert text.startswith("Checking the model openai/gpt-4o...")
    assert text.rstrip().endswith("tool calling works.")


def test_run_check_ollama_prints_header_and_verdict_on_own_line(monkeypatch):
    ok, text = _run_check(
        monkeypatch,
        _run_check_cfg(model="ollama/llama3"),
        _llm_result(
            model="ollama/llama3",
            latency_seconds=1.8,
            ollama_version="0.5.7",
            context_tokens=65536,
            context_source="server",
            tokens_per_second=41.2,
        ),
    )
    assert ok is True
    lines = text.rstrip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("Checking the model ollama/llama3")
    assert "Ollama 0.5.7" in lines[1]
    assert "65,536 tokens (from server)" in lines[1]
    assert "41.2 tok/s" in lines[1]
    assert lines[2].startswith("ok:")


def test_run_check_ollama_includes_warning(monkeypatch):
    ok, text = _run_check(
        monkeypatch,
        _run_check_cfg(model="ollama/llama3"),
        _llm_result(
            model="ollama/llama3",
            latency_seconds=1.9,
            ollama_version="0.5.7",
            context_tokens=8192,
            context_source="server",
            tokens_per_second=39.7,
            context_warning=(
                "Certo: ollama/llama3's context window is below CERTO_CONTEXT_WARN_TOKENS."
            ),
        ),
    )
    assert ok is True
    assert "below CERTO_CONTEXT_WARN_TOKENS" in text
    lines = text.rstrip().splitlines()
    assert len(lines) == 4  # Checking... / header / warning / verdict


def test_run_check_failure_still_shows_details(monkeypatch):
    ok, text = _run_check(
        monkeypatch,
        _run_check_cfg(model="ollama/llama3"),
        _llm_result(
            ok=False,
            model="ollama/llama3",
            latency_seconds=0.2,
            ollama_version="0.5.7",
            context_tokens=8192,
            context_source="server",
            error_kind="setup",
            error="Context window 8192 is below the minimum of 16384",
        ),
    )
    assert ok is False
    assert "Ollama 0.5.7" in text
    assert "8,192" in text
    assert "can't use this model as configured" in text
