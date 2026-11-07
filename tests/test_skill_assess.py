"""Trusted skill repositories: the sources file (skill_sources.py) and
`certo skills assess` (skill_assess.py). No network: the SDK's git fetch is
replaced by a fake repository under tmp_path; loading, license detection,
hashing and the index are real."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from certo import skill_assess as assessing
from certo import third_party_skills as tps
from certo.init_cmd import Prompter
from certo.skill_sources import SourcesError, read_sources
from certo.skills_cmd import skills_main

SHA = "c" * 40
MIT = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a "
    "copy...\n\nThe above copyright notice and this permission notice shall be included in "
    "all copies or substantial portions of the Software.\n"
)


def _skill(root: Path, name: str, frontmatter: str, body: str = "Do the thing.\n") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\n{frontmatter}---\n\n{body}")
    return folder


def _repo(root: Path) -> Path:
    """skills/ holds a usable skill, one to review, one rejected; other/
    holds a skill outside `path: skills`."""
    root.mkdir(parents=True)
    (root / "LICENSE").write_text(MIT)
    skills = root / "skills"
    _skill(
        skills,
        "pytest-helper",
        "description: Write pytest tests for a Python project.\ntriggers:\n- pytest\n",
    )
    scripted = _skill(
        skills,
        "deploy-bot",
        "description: Deploy the app to Vercel.\ntriggers:\n- /deploy\n",
        "Run !`./scripts/go.sh` first.\n",
    )
    (scripted / "scripts").mkdir()
    (scripted / "scripts" / "go.sh").write_text("echo hi\n")
    broken = skills / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("---\nname: Not A Valid Name!\n---\nx\n")
    _skill(root / "other", "elsewhere", "description: Not under skills/.\n")
    (root / ".github" / "hidden").mkdir(parents=True)
    (root / ".github" / "hidden" / "SKILL.md").write_text("---\nname: hidden\n---\nx\n")
    return root


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    upstream = _repo(tmp_path / "upstream")
    calls = []

    def fake(*, source, cache_dir, ref, update, repo_path):
        calls.append({"source": source, "ref": ref, "repo_path": repo_path})
        return (upstream / repo_path if repo_path else upstream), SHA

    monkeypatch.setattr(tps, "fetch_skill_with_resolution", fake)
    return calls


def _sources(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --- the sources file ------------------------------------------------------------------


def test_a_missing_sources_file_lists_nothing(tmp_path):
    assert read_sources(tmp_path / "skill_sources.yaml") == []


def test_sources_are_read_with_their_ref_path_and_skills(tmp_path):
    path = _sources(
        tmp_path / "skill_sources.yaml",
        "sources:\n  - repo: github:OpenHands/extensions\n    ref: main\n    path: skills\n"
        "    skills: [code-review]\n",
    )

    (source,) = read_sources(path)

    assert source.clone_url == "https://github.com/OpenHands/extensions.git"
    assert (source.ref, source.path, source.skills) == ("main", "skills", ("code-review",))
    assert source.label == "github:OpenHands/extensions (skills)"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("sources: nope\n", "needs a `sources:` list"),
        ("sources:\n  - ref: main\n", "each source needs `repo:"),
        ("sources:\n  - repo: git@github.com:a/b.git\n", "Unsupported source"),
        ("sources:\n  - repo: github:a/b\n    branch: x\n", "unknown key(s) branch"),
        ("sources:\n  - repo: github:a/b\n    path: ../up\n", "source 1"),
        ("sources:\n  - repo: github:a/b\n    skills: code-review\n", "a list of skill folder"),
        ("sources:\n  - repo: github:a/b\n  - repo: github:a/b\n", "listed twice"),
    ],
)
def test_a_bad_sources_file_says_what_to_fix(tmp_path, text, error):
    path = _sources(tmp_path / "skill_sources.yaml", text)

    with pytest.raises(SourcesError, match=None) as exc:
        read_sources(path)
    assert error in str(exc.value)


# --- assess ------------------------------------------------------------------------------


def _assess(
    tmp_path, text="sources:\n  - repo: github:acme/skills\n    path: skills\n", reserved=()
):
    skills_dir = tmp_path / "config" / "skills"
    path = _sources(tmp_path / "config" / "skill_sources.yaml", text)
    return skills_dir, assessing.assess(skills_dir, read_sources(path), reserved=reserved)


def test_each_skill_gets_a_verdict_and_a_class(tmp_path, fetch):
    skills_dir, result = _assess(tmp_path)

    (source_result,) = result.results
    assert source_result.revision == SHA
    by_name = {s.name: s for s in source_result.skills}
    assert set(by_name) == {"pytest-helper", "deploy-bot", "broken"}  # path: skills only

    usable = by_name["pytest-helper"]
    assert usable.verdict == assessing.USABLE
    assert usable.steps == ["testing"]
    assert usable.ecosystems == ["python"]
    assert usable.fires_kind == "keywords"
    assert usable.license == "MIT"
    assert usable.integrity.startswith("sha256-")

    review = by_name["deploy-bot"]
    assert review.verdict == assessing.NEEDS_REVIEW
    assert review.fires_kind == "slash command"
    assert "it ships scripts its instructions may ask the agent to run" in review.reasons
    assert any("inline !`command`" in r for r in review.reasons)
    assert "release" in review.steps and "integration" in review.steps

    assert by_name["broken"].verdict == assessing.REJECTED
    assert by_name["broken"].reasons


def test_the_index_and_the_checked_files_are_kept(tmp_path, fetch):
    skills_dir, result = _assess(tmp_path)

    trusted = skills_dir / ".trusted"
    index = json.loads((trusted / "index.json").read_text())
    assert index["sources"][0]["revision"] == SHA
    assert {s["name"] for s in index["skills"]} == {"pytest-helper", "deploy-bot", "broken"}
    kept = {s.name: s.folder for s in assessing.read_index(skills_dir)}
    assert (trusted / kept["pytest-helper"] / "SKILL.md").is_file()
    assert (trusted / kept["deploy-bot"] / "scripts" / "go.sh").is_file()
    assert kept["broken"] is None
    # The repository's license travels with each copy.
    assert (trusted / kept["pytest-helper"] / ".upstream" / "LICENSE").is_file()


def test_assessing_again_replaces_the_index(tmp_path, fetch):
    skills_dir, _ = _assess(tmp_path)
    first = {s.name: s.folder for s in assessing.read_index(skills_dir)}
    assert (skills_dir / ".trusted" / first["deploy-bot"]).is_dir()

    _assess(
        tmp_path,
        "sources:\n  - repo: github:acme/skills\n    path: skills\n"
        "    skills: [pytest-helper, gone]\n",
    )

    names = {s.name: s.verdict for s in assessing.read_index(skills_dir)}
    assert names == {"pytest-helper": assessing.USABLE, "gone": assessing.REJECTED}
    assert not (skills_dir / ".trusted" / first["deploy-bot"]).exists()


def test_a_name_taken_by_an_official_skill_is_rejected(tmp_path, fetch):
    _, result = _assess(tmp_path, reserved=["pytest-helper"])

    found = {s.name: s for s in result.results[0].skills}
    assert found["pytest-helper"].verdict == assessing.REJECTED
    assert found["pytest-helper"].reasons == ["an official skill has the same name"]


def test_the_whole_repository_is_searched_without_a_path(tmp_path, fetch):
    _, result = _assess(tmp_path, "sources:\n  - repo: github:acme/skills\n")

    names = {s.name for s in result.results[0].skills}
    assert "elsewhere" in names
    assert "hidden" not in names  # dot folders are skipped


def test_a_source_that_cant_be_fetched_is_reported(tmp_path, monkeypatch):
    from openhands.sdk.skills.fetch import SkillFetchError

    def fail(**_kw):
        raise SkillFetchError("no network")

    monkeypatch.setattr(tps, "fetch_skill_with_resolution", fail)
    _, result = _assess(tmp_path)

    assert result.results[0].error.startswith("Could not fetch https://github.com/acme/skills.git")
    assert result.results[0].skills == []


# --- the command -------------------------------------------------------------------------


def _cli(tmp_path, monkeypatch, argv):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    out = io.StringIO()
    code = skills_main(argv, prompter=Prompter(out=out), interactive=False, out=out)
    return code, out.getvalue()


def test_assess_without_sources_says_how_to_start(tmp_path, monkeypatch, capsys):
    code, _ = _cli(tmp_path, monkeypatch, ["assess", "--global"])

    err = capsys.readouterr().err
    assert code == 1
    assert "No trusted repositories" in err
    assert "repo: github:OpenHands/extensions" in err


def test_assess_prints_each_verdict(tmp_path, monkeypatch, fetch):
    _sources(
        tmp_path / "xdg" / "certo" / "skill_sources.yaml",
        "sources:\n  - repo: github:acme/skills\n    path: skills\n",
    )

    code, out = _cli(tmp_path, monkeypatch, ["assess", "--global"])

    assert code == 0
    assert (
        "github:acme/skills (skills) at cccccccccccc: 3 skills (1 usable, 1 needs review, 1 rejected)."
        in out
    )
    assert "pytest-helper (testing, python): fires when the task says: pytest; about" in out
    assert "deploy-bot (release, integration): fires when the task says: /deploy" in out
    assert ": 1 usable, 1 to review, 1 rejected. A run adds the usable ones that fit" in out
