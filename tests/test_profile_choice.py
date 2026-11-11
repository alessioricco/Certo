"""profile_choice: the model that goes first for each kind of task, chosen
in a scripted terminal. No model, no network."""

from __future__ import annotations

import yaml
from model_file_helpers import write_split_model_files
from test_init_cmd import Script

from certo.model_catalog import load_model_catalog
from certo.profile_choice import choose_profiles, leave_out_local, set_profile_model

_CATALOG = """
models:
  - name: local
    model: ollama/qwen
    base_url: http://localhost:11434
    ratings: {code: 2, cost: 5}
  - name: luna
    model: openai/luna
    api_key: k
    ratings: {code: 4, cost: 3}
  - name: sol
    model: openai/sol
    api_key: k
    ratings: {code: 5, cost: 1}
  - name: haiku
    model: anthropic/haiku
    api_key: k
    ratings: {code: 3, cost: 4}
task_profiles:
  build:
    triggers: [build, game]
    weights: {code: 3, cost: 1}
  default:
    weights: {cost: 3}
"""

_PROFILES_TEXT = """# My profiles.
task_profiles:
  # Building things.
  build:
    triggers: [build, game]
    weights: {code: 3, cost: 1}

  default:
    weights: {cost: 3}
"""


def _files(tmp_path):
    paths = write_split_model_files(tmp_path, _CATALOG)
    with open(paths["profiles_path"], "w", encoding="utf-8") as f:
        f.write(_PROFILES_TEXT)
    return paths


def _catalog(paths):
    return load_model_catalog(
        paths["list_path"], paths["models_path"], profiles_path=paths["profiles_path"]
    )


def _number(text, label):
    for line in reversed(text.splitlines()):
        if label in line and "." in line:
            return line.split(".", 1)[0].strip()
    raise AssertionError(f"{label!r} not in:\n{text}")


def test_set_profile_model_writes_replaces_and_removes_only_that_line(tmp_path):
    paths = _files(tmp_path)
    path = paths["profiles_path"]

    set_profile_model(path, "build", "luna")
    set_profile_model(path, "default", "haiku")
    assert {p.name: p.model for p in _catalog(paths).task_profiles} == {
        "build": "luna",
        "default": "haiku",
    }
    text = open(path, encoding="utf-8").read()
    assert "# My profiles." in text and "  # Building things." in text

    set_profile_model(path, "build", "sol")
    set_profile_model(path, "default", None)
    assert {p.name: p.model for p in _catalog(paths).task_profiles} == {
        "build": "sol",
        "default": None,
    }
    assert text.count("model:") == 2 and open(path).read().count("model:") == 1


def test_leave_out_local_turns_off_only_the_local_models(tmp_path):
    paths = _files(tmp_path)

    assert leave_out_local(paths["models_path"], _catalog(paths)) == ["local"]

    active = {m.name: m.activated for m in _catalog(paths).models}
    assert active == {"local": False, "luna": True, "sol": True, "haiku": True}
    assert (tmp_path / "models.yaml.bak").exists()


def test_choosing_a_model_per_profile_pins_it(tmp_path):
    paths = _files(tmp_path)

    class Live(Script):
        def _input(self, prompt):
            self.prompts.append(prompt)
            self.out.write(prompt)
            answer = self.answers.pop(0)
            return answer(self.text) if callable(answer) else answer

    script = Live(
        answers=[
            "2",  # no local models
            lambda text: _number(text, "luna  (score"),  # build
            lambda text: _number(text, "Let the ratings decide"),  # default
        ]
    )
    choose_profiles(
        script.prompter(),
        paths["list_path"],
        paths["models_path"],
        paths["profiles_path"],
        {},
    )

    catalog = _catalog(paths)
    assert {p.name: p.model for p in catalog.task_profiles} == {"build": "luna", "default": None}
    assert not next(m for m in catalog.models if m.name == "local").activated
    assert "build (title has: build, game): which model first?" in script.text
    assert "default (when no other kind matches): which model first?" in script.text
    assert "  build: luna\n  default: the ratings decide" in script.text
    personal = yaml.safe_load(open(paths["models_path"]))["models"]
    assert all("api_key" not in m or m["api_key"] == "k" for m in personal)


def test_another_model_can_be_picked_beyond_the_best_three(tmp_path):
    paths = _files(tmp_path)
    script = Script(answers=["1", "5", "1", "4"])  # local too; build: another, the 1st; ratings
    choose_profiles(
        script.prompter(), paths["list_path"], paths["models_path"], paths["profiles_path"], {}
    )
    build = next(p for p in _catalog(paths).task_profiles if p.name == "build")
    # build ranks sol, luna, haiku first; the one left is local.
    assert build.model == "local"
