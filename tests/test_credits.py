"""credits.py: Certo's credit in the projects it creates. No model call."""

from __future__ import annotations

from dataclasses import replace

from certo import credits, runner
from certo.config import Config
from certo.worktree import record_created_project

_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Game</title>
  </head>
  <body></body>
</html>
"""


def test_readme_gets_one_closing_line(tmp_path):
    (tmp_path / "README.md").write_text("# My game\n\nPlay it.\n")

    assert credits.add_readme_credit(str(tmp_path)) is True
    assert credits.add_readme_credit(str(tmp_path)) is False  # once

    text = (tmp_path / "README.md").read_text()
    assert text.endswith(
        "\n---\n\nGenerated with [Certo](https://github.com/alessioricco/Certo).\n"
    )
    assert text.count("Generated with") == 1


def test_index_html_gets_the_generator_meta_tag_inside_head(tmp_path):
    (tmp_path / "index.html").write_text(_PAGE)

    assert credits.add_meta_credit(str(tmp_path / "index.html")) is True
    assert credits.add_meta_credit(str(tmp_path / "index.html")) is False

    text = (tmp_path / "index.html").read_text()
    assert (
        '  <head>\n    <meta name="generator" content="Certo (https://github.com/alessioricco/Certo)">\n'
        in text
    )


def test_a_page_without_head_is_left_alone(tmp_path):
    (tmp_path / "index.html").write_text("<p>hi</p>")

    assert credits.add_meta_credit(str(tmp_path / "index.html")) is False
    assert (tmp_path / "index.html").read_text() == "<p>hi</p>"


def test_build_output_and_dependencies_are_skipped(tmp_path):
    for folder in ("", "public", "dist", "node_modules/pkg", "coverage"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        (tmp_path / folder / "index.html").write_text(_PAGE)

    pages = credits.index_pages(str(tmp_path))

    assert pages == [str(tmp_path / "index.html"), str(tmp_path / "public" / "index.html")]


def _cfg(tmp_path, **overrides) -> Config:
    base = dict(
        model="openai/x",
        api_key="k",
        base_url=None,
        workspace=str(tmp_path / "projects" / "game"),
        max_iterations=5,
        confirm_mode="never",
        execution="local",
        projects_dir=str(tmp_path / "projects"),
    )
    base.update(overrides)
    return Config(**base)


def _project(tmp_path, created: bool):
    project = tmp_path / "projects" / "game"
    project.mkdir(parents=True)
    (project / "README.md").write_text("# Game\n")
    (project / "index.html").write_text(_PAGE)
    if created:
        record_created_project(str(tmp_path / "projects"), "game")
    return project


def test_a_project_certo_created_gets_the_credits_once(tmp_path):
    project = _project(tmp_path, created=True)
    notices: list = []

    runner._add_credits(_cfg(tmp_path), notices.append)
    runner._add_credits(_cfg(tmp_path), notices.append)

    assert "Generated with [Certo]" in (project / "README.md").read_text()
    assert 'name="generator"' in (project / "index.html").read_text()
    assert len(notices) == 1
    text = "".join(c.text for c in notices[0].content)
    assert (
        text == "Certo: added its credit to README.md, index.html (CERTO_CREDITS=no turns it off)."
    )


def test_an_existing_project_is_never_touched(tmp_path):
    project = _project(tmp_path, created=False)

    runner._add_credits(_cfg(tmp_path), lambda m: None)

    assert (project / "README.md").read_text() == "# Game\n"


def test_credits_off(tmp_path):
    project = _project(tmp_path, created=True)

    runner._add_credits(replace(_cfg(tmp_path), credits=False), lambda m: None)

    assert (project / "README.md").read_text() == "# Game\n"


def test_the_setting_is_read_from_the_environment():
    from certo.config import load_config

    env = {"CERTO_LLM_MODEL": "openai/x", "CERTO_LLM_API_KEY": "k", "CERTO_CREDITS": "no"}
    assert load_config(env).credits is False
    assert load_config({**env, "CERTO_CREDITS": "yes"}).credits is True
