"""Matching assessed skills to a project and a task (skill_match.py) and
`certo skills suggest`. Built on a real `assess` of a fake repository: no
network, no model."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from certo import skill_assess as assessing
from certo import skill_match as matching
from certo import third_party_skills as tps
from certo.init_cmd import Prompter
from certo.skill_sources import read_sources
from certo.skills_cmd import skills_main

SHA = "d" * 40
MIT = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a "
    "copy...\n\nThe above copyright notice and this permission notice shall be included in "
    "all copies or substantial portions of the Software.\n"
)
SKILLS = {
    # Fires on its own words; one is a file name.
    "uv": "description: Use uv for Python projects.\ntriggers:\n- uv\n- uv.lock\n",
    # Its words say when it applies, so ecosystem and step alone don't fit it.
    "deno": "description: Deno, for JavaScript and TypeScript tests.\ntriggers:\n- deno\n",
    # Only on request (no triggers): fits by ecosystem and step together.
    "pytest-style": "description: Write pytest tests for Python code.\n",
    # A slash command: fits by ecosystem and step, fires only when named.
    "qa-node": "description: QA review of Node.js changes.\ntriggers:\n- /qa-node\n",
    # An integration: only when the task names it.
    "slack": "description: Post to Slack about tests and releases.\ntriggers:\n- slack\n",
    # Needs review (scripts), fits Python testing.
    "py-runner": "description: Run Python tests with a helper script.\n",
}


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "LICENSE").write_text(MIT)
    for name, frontmatter in SKILLS.items():
        folder = root / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n{frontmatter}---\n\nGuidance.\n")
    (root / "skills" / "py-runner" / "scripts").mkdir()
    (root / "skills" / "py-runner" / "scripts" / "run.sh").write_text("echo\n")
    return root


@pytest.fixture
def config(tmp_path, monkeypatch):
    """An assessed global scope in tmp_path/xdg/certo."""
    upstream = _repo(tmp_path / "upstream")
    monkeypatch.setattr(
        tps,
        "fetch_skill_with_resolution",
        lambda *, source, cache_dir, ref, update, repo_path: (upstream, SHA),
    )
    certo_dir = tmp_path / "xdg" / "certo"
    certo_dir.mkdir(parents=True)
    (certo_dir / "skill_sources.yaml").write_text(
        "sources:\n  - repo: github:acme/skills\n    path: skills\n"
    )
    skills_dir = certo_dir / "skills"
    assessing.assess(skills_dir, read_sources(certo_dir / "skill_sources.yaml"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return skills_dir


def _project(tmp_path: Path, *files: str) -> Path:
    folder = tmp_path / "project"
    folder.mkdir(exist_ok=True)
    for name in files:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if name.endswith(".json") else "")
    return folder


def _names(found):
    return [f.entry.name for f in found]


def test_a_trigger_word_in_the_task_fits(tmp_path, config):
    found = matching.suggest([("global", config)], _project(tmp_path), "Set up uv for this app")

    assert _names(found.fits)[0] == "uv"
    assert found.fits[0].fires_alone == 'the task says "uv"'


def test_a_trigger_word_that_is_a_file_matches_the_project(tmp_path, config):
    found = matching.suggest([("global", config)], _project(tmp_path, "uv.lock", "app.py"))

    assert _names(found.fits) == ["uv"]
    assert "the project has uv.lock" in found.fits[0].reasons


def test_ecosystem_and_step_together_fit_a_skill_without_words(tmp_path, config):
    project = _project(tmp_path, "pyproject.toml")

    found = matching.suggest([("global", config)], project, "Add pytest tests")

    assert "pytest-style" in _names(found.fits)
    fit = next(f for f in found.fits if f.entry.name == "pytest-style")
    assert fit.reasons == ["for python", "about testing"]
    assert fit.fires_alone is None


def test_one_weak_link_is_not_enough(tmp_path, config):
    # A Node project and a task about tests: deno names JavaScript and tests,
    # but its own word, "deno", isn't in the task.
    found = matching.suggest([("global", config)], _project(tmp_path, "package.json"), "Add tests")

    assert "deno" not in _names(found.fits)
    # qa-node (node, testing) has two links here, so it does fit.
    assert "qa-node" in _names(found.fits)
    # Only the ecosystem: nothing for Python fits a Node project either.
    assert "pytest-style" not in _names(found.fits)


def test_a_slash_command_skill_fits_by_ecosystem_and_step(tmp_path, config):
    found = matching.suggest(
        [("global", config)], _project(tmp_path, "package.json"), "Review the changes"
    )

    fit = next(f for f in found.fits if f.entry.name == "qa-node")
    assert fit.fires_alone is None  # it needs /qa-node in the task


def test_an_integration_fits_only_when_the_task_names_it(tmp_path, config):
    project = _project(tmp_path, "pyproject.toml")

    assert "slack" not in _names(matching.suggest([("global", config)], project, "Add tests").fits)
    found = matching.suggest([("global", config)], project, "Tell slack when tests pass")
    assert "slack" in _names(found.fits)


def test_skills_to_review_are_listed_apart(tmp_path, config):
    found = matching.suggest(
        [("global", config)], _project(tmp_path, "pyproject.toml"), "Run the tests"
    )

    assert "py-runner" in _names(found.after_review)
    assert "py-runner" not in _names(found.fits)


def test_a_kept_copy_that_changed_is_never_used(tmp_path, config):
    entry = next(e for e in assessing.read_index(config) if e.name == "uv")
    (assessing.trusted_dir(config) / entry.folder / "SKILL.md").write_text(
        "---\nname: uv\n---\nEvil.\n"
    )

    found = matching.suggest([("global", config)], _project(tmp_path), "Set up uv")

    assert "uv" not in _names(found.fits)


def test_the_project_scope_replaces_a_global_skill_of_the_same_name(tmp_path, config):
    project_skills = tmp_path / "proj-skills"
    project_skills.mkdir()
    import shutil

    shutil.copytree(assessing.trusted_dir(config), assessing.trusted_dir(project_skills))

    found = matching.suggest(
        [("global", config), ("project", project_skills)], _project(tmp_path), "Set up uv"
    )

    assert next(f for f in found.fits if f.entry.name == "uv").scope == "project"


# --- the command -------------------------------------------------------------------------


def _cli(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(_project(tmp_path, "pyproject.toml"))
    out = io.StringIO()
    code = skills_main(argv, prompter=Prompter(out=out), interactive=False, out=out)
    return code, out.getvalue()


def test_suggest_prints_the_fits_and_what_a_run_does(tmp_path, monkeypatch, config):
    code, out = _cli(tmp_path, monkeypatch, ["suggest", "--task", "Set up uv and add pytest tests"])

    assert code == 0
    assert "(python); steps in the task: setup, testing." in out
    assert "uv (global, about " in out and 'the task says "uv"' in out
    assert "; a run adds it" in out
    assert "pytest-style (global, about" in out
    assert "Would fit once reviewed (a run leaves them out):\n  py-runner:" in out


def test_suggest_says_why_a_run_leaves_a_fit_out(tmp_path, monkeypatch, config):
    monkeypatch.chdir(tmp_path)
    node = _node_project(tmp_path)
    monkeypatch.chdir(node)
    out = io.StringIO()
    code = skills_main(
        ["suggest", "--task", "Review the changes"], prompter=Prompter(out=out), interactive=False
    )

    assert code == 0
    assert "qa-node (global, about" in out.getvalue()
    assert "a run leaves it out: only when the task says /qa-node" in out.getvalue()


def test_suggest_before_any_assess_says_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    code, _ = _cli(tmp_path, monkeypatch, ["suggest"])

    assert code == 1
    assert "No assessed skills yet" in capsys.readouterr().err


# --- skills for a run ------------------------------------------------------------------


def _node_project(tmp_path: Path) -> str:
    folder = tmp_path / "node-app"
    folder.mkdir(exist_ok=True)
    (folder / "package.json").write_text("{}")
    return str(folder)


def _run_cfg(tmp_path, config, **overrides):
    from certo.config import Config

    base = dict(
        model="openai/gpt-4o",
        api_key="key",
        base_url=None,
        workspace=str(_project(tmp_path, "pyproject.toml")),
        max_iterations=10,
        confirm_mode="never",
        execution="local",
        global_skills_dir=str(config),
    )
    base.update(overrides)
    return Config(**base)


def test_a_run_gets_the_fitting_skills_as_always_on_context(tmp_path, config):
    picked = matching.skills_for_run(_run_cfg(tmp_path, config), "Set up uv and add pytest tests")

    names = [s.name for s in picked.skills]
    assert names[0] == "uv"
    assert "pytest-style" in names
    for skill in picked.skills:
        assert skill.trigger is None and not skill.is_agentskills_format
    assert picked.notices[0].startswith(
        "Certo: added the trusted skill 'uv' (github:acme/skills, about "
    )
    assert 'the task says "uv"' in picked.notices[0]


def test_skills_to_review_and_unasked_slash_commands_stay_out(tmp_path, config):
    cfg = _run_cfg(tmp_path, config, workspace=_node_project(tmp_path))

    picked = matching.skills_for_run(cfg, "Review the changes and run the tests")

    names = [s.name for s in picked.skills]
    assert "qa-node" not in names  # fits, but its command, /qa-node, isn't in the task
    assert "py-runner" not in names  # needs review


def test_an_asked_slash_command_comes_in(tmp_path, config):
    cfg = _run_cfg(tmp_path, config, workspace=_node_project(tmp_path))

    assert [s.name for s in matching.skills_for_run(cfg, "/qa-node the changes").skills] == [
        "qa-node"
    ]


def test_the_token_budget_bounds_what_comes_in(tmp_path, config):
    cfg = _run_cfg(tmp_path, config, trusted_skills_tokens=1)

    assert matching.skills_for_run(cfg, "Set up uv and add pytest tests").skills == []


def test_zero_turns_trusted_skills_off(tmp_path, config):
    cfg = _run_cfg(tmp_path, config, trusted_skills_tokens=0)

    assert matching.skills_for_run(cfg, "Set up uv").skills == []


def test_a_skill_name_the_run_already_has_wins(tmp_path, config):
    cfg = _run_cfg(tmp_path, config)
    own = Path(cfg.workspace) / ".agents" / "skills" / "uv"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text(
        "---\nname: uv\ndescription: The project's own uv rules.\n---\nx\n"
    )

    picked = matching.skills_for_run(cfg, "Set up uv")

    assert "uv" not in [s.name for s in picked.skills]


def test_the_agent_gets_them_in_its_system_prompt(tmp_path, config):
    from certo.agent import build_agent

    cfg = _run_cfg(tmp_path, config)
    picked = matching.skills_for_run(cfg, "Set up uv")

    agent = build_agent(cfg, trusted_skills=picked.skills)

    repo_skills, _listed = agent.agent_context._partition_skills()
    assert "uv" in [s.name for s in repo_skills]
