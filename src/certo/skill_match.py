"""Which assessed skills (`skill_assess.py`) fit a project and a task.

Rules only, no model call (DECISIONS.md, "Trusted skill repositories"):
a skill fits when something concrete links it to the work, and each link
is a reason the user can read.

- **its trigger**: the task says one of its words (the SDK's own
  `match_trigger`), the strongest link;
- **its paths**: a file in the project matches one of its path triggers,
  or one of its trigger words that is a file name (`uv.lock`,
  `deno.json`);
- a skill whose author gave **trigger words** (not slash commands) applies
  when they fire: when none does and no project file matches, its
  ecosystem and steps don't make it fit (`deno` named JavaScript, and fit
  every Node project);
- **its ecosystems**: they include the project's (`detect_project`, or the
  task's words for a new, empty project). A skill for another ecosystem
  is left out, unless its trigger fired;
- **its steps**: the task's words name one of them ("tests" is testing,
  "fix" is debugging);
- an **integration** skill (Slack, Jira, Kubernetes...) fits only when
  the task names the service, which is its trigger firing.

Scores: trigger 3, path 2, ecosystem 2, each step 1. A skill fits from
`MIN_SCORE` (3): its trigger alone, or two links together (an ecosystem
and a step, a path and a step). One weak link isn't enough: on
OpenHands/extensions (2026-11-07) "the project is Node" alone suggested
`npm` and `deno` for every Node project, and "the task mentions tests"
alone suggested `kubernetes` for a Python CLI.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openhands.sdk.skills import KeywordTrigger, PathTrigger, Skill, TaskTrigger
from openhands.sdk.skills.utils import find_skill_md

from . import skill_assess as assessing
from . import skill_library as lib
from . import third_party_skills as tps

_LANGUAGE_ECOSYSTEM = {
    "python": "python",
    "node": "node",
    "go": "go",
    "rust": "rust",
    "java-maven": "java",
    "java-gradle": "java",
}
# Folders never read when listing a project's files.
_SKIP_DIRS = {".git", ".certo", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
_MAX_FILES = 5000
MIN_SCORE = 3


@dataclass
class Fit:
    entry: assessing.Assessed
    scope: str  # "global" or "project"
    score: int
    reasons: list[str] = field(default_factory=list)
    fires_alone: str | None = None  # why a run would load it from the task alone
    skill: Skill | None = None  # the kept copy, checked against its hash


@dataclass
class Suggestions:
    fits: list[Fit]  # usable skills, best first
    after_review: list[Fit]  # skills that would fit once reviewed
    project_ecosystems: list[str]
    task_steps: list[str]
    indexed: int  # assessed skills read from the indexes


def project_files(folder: Path) -> list[str]:
    """The project's files, relative, without dependency and build folders."""
    found: list[str] = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            found.append(Path(current, name).relative_to(folder).as_posix())
            if len(found) >= _MAX_FILES:
                return found
    return found


def project_ecosystems(folder: Path, files: list[str], task: str) -> list[str]:
    from .verification import detect_project

    found: list[str] = []
    detection = detect_project(str(folder))
    candidates = detection.candidates or ((detection.language, detection.root),)
    for language, _root in candidates:
        eco = _LANGUAGE_ECOSYSTEM.get(language)
        if eco and eco not in found:
            found.append(eco)
    if any(f.endswith((".html", ".css")) for f in files) and "web" not in found:
        found.append("web")
    # A new project has no files yet: the task says what it will be.
    text = task.lower()
    for eco, words in assessing._ECOSYSTEMS:
        if eco not in found and assessing._mentions(text, words):
            found.append(eco)
    return found


def task_steps(task: str) -> list[str]:
    text = task.lower()
    steps = [step for step, words in assessing._STEPS if assessing._mentions(text, words)]
    return [s for s in steps if s != "integration"]


def load_kept(skills_dir: Path, entry: assessing.Assessed) -> Skill | None:
    """The kept copy of an assessed skill, if its files still match the
    hash in the index; inline commands escaped, as for every third-party
    skill."""
    if entry.folder is None or entry.integrity is None:
        return None
    folder = assessing.trusted_dir(skills_dir) / entry.folder
    try:
        if not folder.is_dir() or tps.compute_integrity(folder) != entry.integrity:
            return None
        skill = Skill.load(find_skill_md(folder), strict=True, skip_mcp=True)
    except (tps.ThirdPartySkillError, *tps.SKILL_LOAD_ERRORS):
        return None
    return lib.untrusted(skill)


def _file_hit(trigger: object, files: list[str]) -> str | None:
    """The first project file that a path trigger, or a trigger word that is
    a file name (`uv.lock`), matches."""
    patterns: list[str] = []
    if isinstance(trigger, PathTrigger):
        patterns = list(trigger.paths)
    elif isinstance(trigger, KeywordTrigger | TaskTrigger):
        words = trigger.keywords if isinstance(trigger, KeywordTrigger) else trigger.triggers
        patterns = [w for w in words if "." in w and " " not in w and not w.startswith("/")]
    for name in files:
        base = name.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(base, p) for p in patterns):
            return name
    return None


def _fit(
    entry: assessing.Assessed,
    skill: Skill,
    scope: str,
    task: str,
    files: list[str],
    ecosystems: list[str],
    steps: list[str],
) -> Fit | None:
    score, reasons = 0, []
    fires_alone = None
    trigger = skill.trigger
    if isinstance(trigger, KeywordTrigger | TaskTrigger) and task:
        word = skill.match_trigger(task)
        if word:
            score += 3
            fires_alone = f'the task says "{word}"'
            reasons.append(fires_alone)
    hit = _file_hit(trigger, files)
    if hit:
        score += 2
        reasons.append(f"the project has {hit}")
    if entry.fires_kind == "keywords" and fires_alone is None and hit is None:
        return None  # its own words say when it applies, and none did
    if entry.ecosystems:
        shared = [e for e in entry.ecosystems if e in ecosystems]
        if shared:
            score += 2
            reasons.append(f"for {', '.join(shared)}")
        elif fires_alone is None:
            return None  # made for another ecosystem
    if "integration" in entry.steps and fires_alone is None:
        return None  # a service the task doesn't name
    shared_steps = [s for s in entry.steps if s in steps]
    if shared_steps:
        score += len(shared_steps)
        reasons.append(f"about {', '.join(shared_steps)}")
    if score < MIN_SCORE:
        return None
    return Fit(entry, scope, score, reasons, fires_alone, skill)


def suggest(scopes: list[tuple[str, Path]], workspace: Path | None, task: str = "") -> Suggestions:
    """Match the indexes of `scopes` (`(name, skills_dir)`, lowest first: a
    later scope's skill replaces an earlier one of the same name) against
    the project in `workspace` (None: no project) and `task`."""
    by_name: dict[str, tuple[str, Path, assessing.Assessed]] = {}
    indexed = 0
    for scope, skills_dir in scopes:
        for entry in assessing.read_index(skills_dir):
            indexed += 1
            if entry.verdict != assessing.REJECTED:
                by_name[entry.name] = (scope, skills_dir, entry)
    if not by_name:
        # Nothing assessed (most runs): don't walk the project at all.
        return Suggestions([], [], [], [], indexed)
    files = project_files(workspace) if workspace is not None and workspace.is_dir() else []
    ecosystems = (
        project_ecosystems(workspace, files, task)
        if workspace is not None
        else [e for e, w in assessing._ECOSYSTEMS if assessing._mentions(task.lower(), w)]
    )
    steps = task_steps(task)
    fits: list[Fit] = []
    after_review: list[Fit] = []
    for scope, skills_dir, entry in by_name.values():
        skill = load_kept(skills_dir, entry)
        if skill is None:
            continue
        fit = _fit(entry, skill, scope, task, files, ecosystems, steps)
        if fit is None:
            continue
        (fits if entry.verdict == assessing.USABLE else after_review).append(fit)
    order = lambda f: (-f.score, f.entry.tokens, f.entry.name)  # noqa: E731
    return Suggestions(
        sorted(fits, key=order), sorted(after_review, key=order), ecosystems, steps, indexed
    )


@dataclass
class RunSkills:
    """The trusted skills a run gets, one line about each, and why the other
    fits are left out (`certo skills suggest` shows it)."""

    skills: list[Skill]
    notices: list[str]
    left_out: dict[str, str] = field(default_factory=dict)
    found: Suggestions | None = None


def skills_for_run(cfg: Any, task: str) -> RunSkills:
    """The usable trusted skills that fit this run's folder and task, as
    always-on context, best first, within `cfg.trusted_skills_tokens`.

    A skill whose name a run already has (official, yours, the project's
    own) is left out: those win. So is a slash-command skill whose command
    isn't in the task: its author meant it to be asked for by name. Each
    one added is a copy with no trigger, so the SDK puts its whole content
    in the system prompt for this run (`AgentContext._partition_skills`,
    SDK 1.47)."""
    workspace = Path(cfg.workspace)
    global_root = Path(cfg.global_skills_dir) if cfg.global_skills_dir else lib.global_dir()
    scopes = [("global", global_root), ("project", lib.project_dir(workspace))]
    found = suggest(scopes, workspace, task)
    picked = RunSkills([], [], found=found)
    if not found.fits:
        return picked
    taken = {row.name for row in lib.collect(cfg, workspace).rows if row.skill is not None}
    budget = cfg.trusted_skills_tokens
    for fit in found.fits:
        name = fit.entry.name
        if budget <= 0 and cfg.trusted_skills_tokens <= 0:
            picked.left_out[name] = "CERTO_TRUSTED_SKILLS_TOKENS is 0"
        elif fit.skill is None:
            picked.left_out[name] = "its files changed since assess"
        elif name in taken:
            picked.left_out[name] = "the run already has a skill of that name"
        elif fit.entry.fires_kind == "slash command" and fit.fires_alone is None:
            command = fit.entry.fires.rsplit(": ", 1)[-1]
            picked.left_out[name] = f"only when the task says {command}"
        elif fit.entry.tokens > budget:
            picked.left_out[name] = "over the CERTO_TRUSTED_SKILLS_TOKENS budget"
        else:
            budget -= fit.entry.tokens
            picked.skills.append(
                fit.skill.model_copy(update={"trigger": None, "is_agentskills_format": False})
            )
            picked.notices.append(
                f"Certo: added the trusted skill '{name}' ({fit.entry.repo}, "
                f"about {fit.entry.tokens:,} tokens): {', '.join(fit.reasons)}."
            )
    return picked
