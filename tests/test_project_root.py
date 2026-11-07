"""Choosing the project root from the task (project_root.py): no model,
no network."""

from __future__ import annotations

import pytest

from certo.project_root import (
    is_certo_workspace,
    project_name_for_task,
    slugify,
    unused_project_name,
)


@pytest.mark.parametrize(
    ("source", "text", "name"),
    [
        # A task file or URL: its name.
        ("tasks/wordle.md", "# Wordle\n\nBuild Wordle.", "wordle"),
        ("tasks/Space Rocks.md", "Anything", "space-rocks"),
        ("https://example.com/specs/crypto-dashboard.md", "x", "crypto-dashboard"),
        # A file named only "task" says nothing: its title is used.
        ("specs/task.md", "# Todo List API\n\n...", "todo-list-api"),
        # Text: the Markdown title, else the first words without filler.
        ("# Tower of Hanoi\nSolve it", "# Tower of Hanoi\nSolve it", "tower-hanoi"),
        (
            "Build a polished cryptocurrency market dashboard as a web app in this workspace.",
            "Build a polished cryptocurrency market dashboard as a web app in this workspace.",
            "polished-cryptocurrency-market-dashboard",
        ),
        (
            "A command-line to-do list in Python",
            "A command-line to-do list in Python",
            "command-line-to-do-list-python",
        ),
        ("Build an app", "Build an app", "project"),
    ],
)
def test_the_name_comes_from_the_task(source, text, name):
    assert project_name_for_task(source, text) == name


def test_a_slug_is_short_and_cut_at_a_hyphen():
    slug = slugify("A very long title that goes on and on well past forty characters")
    assert len(slug) <= 40
    assert not slug.endswith("-")
    assert slug == "a-very-long-title-that-goes-on-and-on"


def test_an_existing_folder_gets_a_number(tmp_path):
    (tmp_path / "wordle").mkdir()
    (tmp_path / "wordle-2").mkdir()

    assert unused_project_name(str(tmp_path), "wordle") == "wordle-3"
    assert unused_project_name(str(tmp_path), "hanoi") == "hanoi"


def test_a_workspace_has_a_projects_folder_and_is_no_project(tmp_path):
    projects = tmp_path / "projects"
    assert not is_certo_workspace(str(tmp_path), str(projects))

    projects.mkdir()
    assert is_certo_workspace(str(tmp_path), str(projects))
    # Projects inside it don't make it one.
    (projects / "app").mkdir()
    (projects / "app" / "package.json").write_text("{}")
    assert is_certo_workspace(str(tmp_path), str(projects))

    # A folder that is a project itself keeps working in place.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert not is_certo_workspace(str(tmp_path), str(projects))
