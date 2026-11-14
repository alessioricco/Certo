"""skill_library.py tests: the layers a run's skills come from, what
replaces what, and how a skill fires. Real SDK loading, no network."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from certo import skill_library as lib
from certo import third_party_skills as tps
from certo.agent import build_agent
from certo.config import load_config

KEYWORD_SKILL = """---
name: {name}
triggers:
  - snake
---
{body}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A clean user folder and current folder."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _cfg(tmp_path: Path):
    return load_config({"CERTO_LLM_MODEL": "openai/gpt-4o", "CERTO_LLM_API_KEY": "k"})


def _write(folder: Path, name: str, body: str = "Short functions.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    path.write_text(KEYWORD_SKILL.format(name=name, body=body))
    return path


def _rows(found: lib.SkillSet, layer: str) -> dict[str, lib.SkillRow]:
    return {r.name: r for r in found.rows if r.layer == layer}


def test_official_global_and_project_layers(home):
    _write(lib.global_dir(), "my-style")
    project = home / "projects" / "demo"
    _write(lib.project_dir(project), "game-rules")

    found = lib.collect(_cfg(home), project)

    assert "testing-and-verification" in _rows(found, lib.OFFICIAL)
    assert set(_rows(found, lib.GLOBAL)) == {"my-style"}
    assert set(_rows(found, lib.PROJECT)) == {"game-rules"}
    names = {s.name for s in found.skills}
    assert {"my-style", "game-rules", "testing-and-verification"} <= names
    assert found.notices == ()


def test_a_third_party_skill_replaces_an_official_one_and_a_run_says_so(home):
    _write(lib.global_dir(), "pytest-conventions", "Mine.")

    found = lib.collect(_cfg(home), None)

    official = _rows(found, lib.OFFICIAL)["pytest-conventions"]
    assert official.replaced_by == lib.GLOBAL and not official.active
    assert [s.content.strip() for s in found.skills if s.name == "pytest-conventions"] == ["Mine."]
    assert found.notices == (
        "Certo: your global skill 'pytest-conventions' replaces the official one.",
    )


def test_a_project_skill_replaces_a_global_one(home):
    _write(lib.global_dir(), "my-style", "Global.")
    project = home / "p"
    _write(lib.project_dir(project), "my-style", "Project.")

    found = lib.collect(_cfg(home), project)

    assert _rows(found, lib.GLOBAL)["my-style"].replaced_by == lib.PROJECT
    assert [s.content.strip() for s in found.skills if s.name == "my-style"] == ["Project."]


def test_the_projects_own_skills_are_listed_and_left_to_the_sdk(home):
    project = home / "p"
    (project / ".agents" / "skills").mkdir(parents=True)
    _write(project / ".agents" / "skills", "own-rule")

    found = lib.collect(_cfg(home), project)

    assert "own-rule" in _rows(found, lib.OWN)
    assert "own-rule" not in {s.name for s in found.skills}
    assert lib.collect(_cfg(home), project, own=False).rows == tuple(
        r for r in found.rows if r.layer != lib.OWN
    )


def _project_inside_a_repo(home: Path) -> Path:
    """A generated project under a repository that has its own agent files,
    like a project under Certo's `projects/`."""
    repo = home / "repo"
    (repo / ".git").mkdir(parents=True)
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules"):
        (repo / name).write_text("REPO-RULES\n")
    _write(repo / ".agents" / "skills", "repo-skill")
    project = repo / "projects" / "demo"
    project.mkdir(parents=True)
    return project


def _cfg_for(home: Path, project: Path, **changes):
    changes = {"workspace": str(project), "projects_dir": str(project.parent), **changes}
    return replace(_cfg(home), **changes)


REPO_SKILLS = ["agents", "claude", "cursorrules", "gemini", "repo-skill"]


def test_a_generated_project_gets_no_agent_files_from_a_repo_above_it(home):
    project = _project_inside_a_repo(home)
    cfg = _cfg_for(home, project)

    assert lib.disabled_project_skills(project, cfg.projects_dir) == REPO_SKILLS
    assert _rows(lib.collect(cfg, project), lib.OWN) == {}
    assert build_agent(cfg).agent_context.disabled_skills == REPO_SKILLS


def test_a_generated_projects_own_agent_files_count(home):
    project = _project_inside_a_repo(home)
    (project / "CLAUDE.md").write_text("PROJECT-RULES\n")
    _write(project / ".agents" / "skills", "repo-skill", "Project copy.")
    cfg = _cfg_for(home, project)

    assert lib.disabled_project_skills(project, cfg.projects_dir) == [
        "agents",
        "cursorrules",
        "gemini",
    ]
    own = _rows(lib.collect(cfg, project), lib.OWN)
    assert set(own) == {"claude", "repo-skill"}
    assert own["claude"].skill.content.strip() == "PROJECT-RULES"


def test_an_existing_folder_keeps_the_agent_files_of_its_repo(home):
    project = _project_inside_a_repo(home)
    cfg = _cfg_for(home, project, projects_dir=str(home / "elsewhere"))

    assert lib.disabled_project_skills(project, cfg.projects_dir) == []
    assert set(_rows(lib.collect(cfg, project), lib.OWN)) == set(REPO_SKILLS)
    assert build_agent(cfg).agent_context.disabled_skills == []


@pytest.mark.parametrize("local", [False, True])
def test_a_run_on_a_generated_project_gets_only_its_own_agent_files(home, local):
    # The real SDK path: the Conversation loads project skills lazily, from
    # the workspace and the git repo root, then applies disabled_skills.
    from openhands.sdk import Conversation

    project = _project_inside_a_repo(home)
    if local:
        (project / "CLAUDE.md").write_text("PROJECT-RULES\n")
    cfg = _cfg_for(home, project, model="anthropic/claude-haiku-4-5")
    conversation = Conversation(agent=build_agent(cfg), workspace=str(project), visualizer=None)

    conversation.send_message("hello")  # loads the project skills; no model call

    loaded = {s.name: s.content.strip() for s in conversation.agent.agent_context.skills}
    assert not set(loaded) & (set(REPO_SKILLS) - {"claude"})
    assert loaded.get("claude") == ("PROJECT-RULES" if local else None)


def test_only_the_top_level_is_read_never_a_git_cache(home):
    root = lib.global_dir()
    _write(root / ".cache" / "repo", "from-cache")
    _write(root / "nested", "deep")  # a folder without SKILL.md
    (root / "README.md").write_text("not a skill")

    rows = _rows(lib.collect(_cfg(home), None), lib.GLOBAL)

    assert "from-cache" not in rows and "deep" not in rows and "README" not in rows
    assert rows["nested"].state.startswith("can't load")


def test_inline_commands_in_a_third_party_skill_are_escaped(home):
    _write(lib.global_dir(), "risky", "Run !`rm -rf /` now.")

    skill = next(s for s in lib.collect(_cfg(home), None).skills if s.name == "risky")

    assert "\\!`rm -rf /`" in skill.content


def test_a_downloaded_skill_is_off_until_enabled(home, monkeypatch):
    root = lib.global_dir()
    root.mkdir(parents=True)
    entry = tps.LockEntry(
        source="https://github.com/o/r.git",
        path="skills/dl",
        revision="a" * 40,
        requested_ref=None,
        license="MIT",
        license_files=[],
        license_notes=[],
        license_url=None,
        source_url="https://github.com/o/r/tree/x/skills/dl",
        integrity="",
    )
    (root / "dl").mkdir()
    (root / "dl" / "SKILL.md").write_text("---\nname: dl\ndescription: d\n---\nBody\n")
    entry.integrity = tps.compute_integrity(root / "dl")
    tps.write_lock(lib.lock_path(root), {"dl": entry})

    row = _rows(lib.collect(_cfg(home), None), lib.GLOBAL)["dl"]
    assert row.skill is None and row.downloaded
    assert row.state == "off (downloaded; turn it on with: certo skills enable dl --global)"

    tps.set_enabled("dl", True, install_dir=root, lock_path=lib.lock_path(root))
    assert _rows(lib.collect(_cfg(home), None), lib.GLOBAL)["dl"].active


def test_how_a_skill_fires_and_for_which_task(home):
    official = {r.name: r.skill for r in lib.collect(_cfg(home), None).rows}

    pytest_skill = official["pytest-conventions"]
    assert (
        lib.how_it_fires(pytest_skill) == "when the task says: pytest, python, unittest, conftest"
    )
    assert lib.fires_for_task(pytest_skill, "Add pytest tests") == '"pytest" is in the task'
    assert lib.fires_for_task(pytest_skill, "Write a poem") is None
    pins = official["pin-dependencies"]
    assert lib.how_it_fires(pins).startswith("when the agent touches: pyproject.toml")
    assert lib.later_for_task(pins).startswith("if the agent touches pyproject.toml")
    assert lib.size_in_tokens(pytest_skill) > 0


def test_a_run_gets_the_global_skill(home):
    _write(lib.global_dir(), "my-style")
    cfg = _cfg(home)

    agent = build_agent(cfg)

    assert "my-style" in {s.name for s in agent.agent_context.skills}


def test_skills_off_leaves_out_official_skills_only(home):
    # A bench arm's skills_off: the official skill goes; a third-party one
    # of the same name, which replaces it, stays.
    _write(lib.global_dir(), "pytest-conventions", "Mine.")

    found = lib.collect(_cfg(home), None)
    kept = {s.name: s for s in found.without_official(["pytest-conventions", "security-review"])}

    assert "security-review" not in kept
    assert kept["pytest-conventions"].content.strip() == "Mine."
    assert "testing-and-verification" in kept


def test_an_agent_with_skills_off_does_not_get_them(home):
    cfg = replace(_cfg(home), skills_off=("security-review",))

    names = {s.name for s in build_agent(cfg).agent_context.skills}

    assert "security-review" not in names
    assert "testing-and-verification" in names


def test_pytest_conventions_stays_out_of_a_javascript_game(home, tmp_path):
    # Its old trigger, "test", put it in every task that asks for tests.
    official = {r.name: r.skill for r in lib.collect(_cfg(home), None).rows}
    pytest_skill = official["pytest-conventions"]

    assert lib.fires_for_task(pytest_skill, "Build a browser game with tests") is None
    assert (
        lib.fires_for_task(pytest_skill, "Write a Python CLI with tests")
        == '"python" is in the task'
    )


def test_the_language_gate_leaves_out_skills_for_another_language(tmp_path):
    node = tmp_path / "game"
    node.mkdir()
    (node / "package.json").write_text("{}")
    py = tmp_path / "tool"
    py.mkdir()
    (py / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    assert lib.off_for_language(lib.project_language(node)) == ["pytest-conventions"]
    assert lib.off_for_language(lib.project_language(py)) == []
    assert lib.off_for_language(lib.project_language(tmp_path / "missing")) == []


def test_a_run_in_a_node_project_never_gets_pytest_conventions(home, tmp_path):
    (tmp_path / "package.json").write_text("{}")
    cfg = _cfg(home)
    from dataclasses import replace

    agent = build_agent(replace(cfg, workspace=str(tmp_path)))

    assert "pytest-conventions" not in {s.name for s in agent.agent_context.skills}
