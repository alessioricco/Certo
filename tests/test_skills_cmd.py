"""`certo skills` tests: list, add, remove and the git commands, with real
skill loading and the SDK's git fetch faked (no network)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from test_third_party_skills import FakeFetch, _make_upstream

from certo import cli
from certo import skill_library as lib
from certo import third_party_skills as tps
from certo.init_cmd import Prompter
from certo.skills_cmd import skills_main

SKILL = """---
name: {name}
triggers:
  - snake
---
Short functions.
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CERTO_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.delenv("CERTO_LLM_MODEL", raising=False)  # skills need no model
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    return tmp_path


def _run(argv, answers=(), interactive=False):
    out = io.StringIO()
    replies = iter(answers)
    prompter = Prompter(input_fn=lambda _p: next(replies), out=out, menus=False)
    code = skills_main(argv, prompter=prompter, interactive=interactive)
    return code, out.getvalue()


def _skill_file(folder: Path, name: str = "my-style") -> Path:
    path = folder / f"{name}.md"
    path.write_text(SKILL.format(name=name))
    return path


def test_add_needs_global_or_project(home):
    with pytest.raises(SystemExit) as exc:
        _run(["add", str(_skill_file(home))])
    assert exc.value.code == 2


def test_add_a_file_globally_and_list_it(home):
    code, out = _run(["add", str(_skill_file(home)), "--global"])

    assert code == 0
    assert "Added 'my-style' to " in out and "It is on." in out
    assert "Fires when the task says: snake; about " in out
    assert (lib.global_dir() / "my-style.md").is_file()

    code, out = _run(["list"])
    assert code == 0
    assert "Official skills (come with Certo; a release changes them):" in out
    assert "Your global skills, in " in out
    assert "  my-style: when the task says: snake; about " in out
    assert "Add --project NAME to see a project's skills too." in out


def test_add_a_folder_to_a_project_keeps_it_out_of_git(home):
    folder = home / "game-rules"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: game-rules\ndescription: Rules.\n---\nBody\n")

    code, out = _run(["add", str(folder), "--project", "demo"])

    assert code == 0
    project = home / "projects" / "demo"
    assert (lib.project_dir(project) / "game-rules" / "SKILL.md").is_file()
    assert (project / ".certo" / ".gitignore").is_file()  # .certo/ ignores itself
    assert "Fires when the agent asks for it" in out


def test_adding_a_skill_of_the_same_name_asks_first(home):
    path = _skill_file(home)
    _run(["add", str(path), "--global"])

    code, out = _run(["add", str(path), "--global"], answers=["n"], interactive=True)
    assert code == 0 and "Nothing changed." in out

    code, _out = _run(["add", str(path), "--global"])  # no terminal, no --yes
    assert code == 1

    code, out = _run(["add", str(path), "--global", "--yes"])
    assert code == 0 and "Added 'my-style'" in out


def test_replacing_an_official_skill_is_said(home):
    code, out = _run(["add", str(_skill_file(home, "pytest-conventions")), "--global"])

    assert code == 0
    assert "It replaces the official skill 'pytest-conventions'; a run says so." in out


def test_a_file_that_is_not_a_skill_is_refused(home):
    (home / "notes.txt").write_text("hello")
    empty = home / "empty"
    empty.mkdir()

    assert _run(["add", str(home / "notes.txt"), "--global"])[0] == 1
    assert _run(["add", str(empty), "--global"])[0] == 1
    assert not lib.global_dir().exists()


def test_a_missing_path_without_a_repository_path_explains_the_git_form(home, capsys):
    code, _out = _run(["add", "github:o/r", "--global"])

    assert code == 1
    assert "certo skills add github:OWNER/REPO skills/NAME --global" in capsys.readouterr().err


def test_remove_a_skill_but_never_an_official_one(home, capsys):
    _run(["add", str(_skill_file(home)), "--global"])

    code, out = _run(["remove", "my-style", "--global"])
    assert code == 0 and "Removed 'my-style'" in out
    assert not (lib.global_dir() / "my-style.md").exists()

    code, _out = _run(["remove", "pytest-conventions", "--global"])
    assert code == 1
    assert "is an official skill" in capsys.readouterr().err


def test_list_for_a_task_says_what_goes_in_and_why(home):
    _run(["add", str(_skill_file(home)), "--project", "demo"])

    code, out = _run(["list", "--project", "demo", "--task", "Build a snake game"])

    assert code == 0
    assert "This project's skills, in " in out
    assert "For the task 'Build a snake game':" in out
    assert '    my-style (project): "snake" is in the task' in out
    assert '    repository-discovery (official): "build" is in the task' in out


def test_list_for_a_task_reads_a_task_file(home):
    task = home / "game.md"
    task.write_text("# A snake game in the browser\n\nBuild it with tests.\n")

    code, out = _run(["list", "--task", str(task)])

    assert code == 0
    assert "For the task 'A snake game in the browser':" in out
    assert '    testable-interactive-apps (official): "game" is in the task' in out


def test_an_unknown_project_is_an_error(home, capsys):
    assert _run(["list", "--project", "nope"])[0] == 1
    assert "There is no project 'nope'" in capsys.readouterr().err


def test_a_git_skill_is_downloaded_off_then_enabled(home, monkeypatch):
    monkeypatch.setattr(
        tps, "fetch_skill_with_resolution", FakeFetch(_make_upstream(home / "upstream"))
    )

    code, out = _run(["add", "github:demo/skills", "skills/demo-skill", "--global"])
    assert code == 0
    assert "Downloaded 'demo-skill' to " in out and "It is off." in out
    assert "certo skills enable demo-skill --global" in out
    row = next(r for r in lib.collect(_load(), None).rows if r.name == "demo-skill")
    assert not row.active

    assert _run(["enable", "demo-skill", "--global"])[0] == 0
    row = next(r for r in lib.collect(_load(), None).rows if r.name == "demo-skill")
    assert row.active

    assert _run(["disable", "demo-skill", "--global"])[0] == 0
    assert _run(["remove", "demo-skill", "--global"])[0] == 0
    assert not (lib.global_dir() / "demo-skill").exists()


def test_enable_refuses_a_skill_added_from_a_file(home, capsys):
    _run(["add", str(_skill_file(home)), "--global"])

    assert _run(["enable", "my-style", "--global"])[0] == 1
    assert "always on" in capsys.readouterr().err


def test_skills_is_a_certo_subcommand(home, capsys):
    assert cli.main(["skills", "list"]) == 0
    assert "Official skills" in capsys.readouterr().out


def _load():
    from certo.config import defer_llm_check, load_config

    with defer_llm_check():
        return load_config()


def test_project_dot_is_the_current_folder(home, monkeypatch):
    monkeypatch.setenv("CERTO_WORKSPACE", str(home / "here"))
    (home / "here").mkdir()

    code, _out = _run(["add", str(_skill_file(home)), "--project", "."])
    assert code == 0
    assert (home / "here" / ".certo" / "skills" / "my-style.md").is_file()

    code, out = _run(["list", "--project", "."])
    assert code == 0 and "  my-style: when the task says: snake" in out
