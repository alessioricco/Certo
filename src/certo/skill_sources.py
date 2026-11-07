"""Trusted skill repositories: the sources file.

`skill_sources.yaml` names the git repositories whose skills Certo may
use: `~/.config/certo/skill_sources.yaml` for every project, and
`<project>/.certo/skill_sources.yaml` for one. Each scope is assessed on
its own (`skill_assess.py`) into its own index; at run time the project's
index wins over the global one, as the skill layers do (TODO.md, "Trusted
skill repositories").

    sources:
      - repo: github:OpenHands/extensions
        ref: main            # a branch, tag or commit; assess records the commit
        path: skills         # optional: only the skills under this folder
        skills: [code-review, qa-changes]   # optional: only these skill folders

Listing a repository is the trust; `assess` decides which of its skills
are usable without `certo skills enable` (DECISIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import third_party_skills as tps

SOURCES_FILE = "skill_sources.yaml"

EXAMPLE = """sources:
  - repo: github:OpenHands/extensions
    ref: main
    path: skills
"""


class SourcesError(Exception):
    """A sources file Certo can't use; the message says what to fix."""


@dataclass(frozen=True)
class Source:
    """One trusted repository."""

    repo: str  # as written: github:OWNER/REPO or an https:// git URL
    clone_url: str
    web_base: str | None
    ref: str | None
    path: str | None  # the folder to look for skills in, None for the whole repository
    skills: tuple[str, ...] | None  # only these skill folders; None for all

    @property
    def label(self) -> str:
        return self.repo + (f" ({self.path})" if self.path else "")


def sources_path(skills_dir: Path) -> Path:
    """The sources file of a third-party skills folder's scope: next to it,
    in `~/.config/certo/` or `<project>/.certo/`."""
    return skills_dir.parent / SOURCES_FILE


def read_sources(path: Path) -> list[Source]:
    """The sources in `path`; [] when the file doesn't exist."""
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SourcesError(f"{path} isn't valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sources", []), list):
        raise SourcesError(f"{path} needs a `sources:` list, for example:\n{EXAMPLE}")
    found: list[Source] = []
    seen: set[str] = set()
    for number, item in enumerate(data.get("sources") or [], start=1):
        where = f"{path}, source {number}"
        if not isinstance(item, dict) or not isinstance(item.get("repo"), str):
            raise SourcesError(f"{where}: each source needs `repo: github:OWNER/REPO`.")
        unknown = set(item) - {"repo", "ref", "path", "skills"}
        if unknown:
            raise SourcesError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}.")
        try:
            clone_url, web_base = tps.parse_source(item["repo"])
            folder = tps.validate_skill_path(item["path"]) if item.get("path") else None
        except tps.ThirdPartySkillError as exc:
            raise SourcesError(f"{where}: {exc}") from exc
        ref = item.get("ref")
        if ref is not None and not isinstance(ref, str | int):
            raise SourcesError(f"{where}: `ref` is a branch, tag or commit.")
        skills = item.get("skills")
        if skills is not None and (
            not isinstance(skills, list) or not all(isinstance(s, str) and s for s in skills)
        ):
            raise SourcesError(f"{where}: `skills` is a list of skill folder names.")
        key = f"{clone_url} {folder}"
        if key in seen:
            raise SourcesError(f"{where}: {item['repo']} is listed twice.")
        seen.add(key)
        found.append(
            Source(
                repo=item["repo"].strip(),
                clone_url=clone_url,
                web_base=web_base,
                ref=str(ref) if ref is not None else None,
                path=folder,
                skills=tuple(skills) if skills is not None else None,
            )
        )
    return found
