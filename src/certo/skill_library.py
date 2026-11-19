"""Where a run's skills come from, in order, and what `certo skills` shows.

Layers, lowest to highest; a skill replaces one of the same name below it:

1. official: Certo's own, in the package (`certo/builtin_skills/`),
   changed only by a release;
2. third-party, global: `~/.config/certo/skills/`, for every project;
3. third-party, project: `<project>/.certo/skills/`, never in git
   (`.certo/` ignores itself);
4. the project's own `.agents/skills/` and `AGENTS.md`: loaded by the SDK
   itself (`load_project_skills`, which overrides a same-named skill), only
   read here, never written. A project Certo generates gets only what is
   inside its folder, never the agent files of a git repository above it
   (`disabled_project_skills`).

A third-party folder holds, at its top level only, `<name>.md` files and
`<name>/SKILL.md` folders. A skill added from a file or folder is on as
soon as it is there; a skill downloaded from git is listed in the folder's
`skills.lock.json` and stays off until enabled, with its license and hash
checked (`third_party_skills.py`). The folder's `official-off.json` lists
the official skills turned off there (`certo skills disable NAME`): for
every project in the global folder, for one in a project's. Names starting with a dot (the git
cache, staging) are never skills. Nothing here is loaded recursively: a
git cache holds whole repositories.

Every third-party skill is untrusted text: its inline `` !`command` `` is
escaped and its `.mcp.json` ignored, as for downloaded skills.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from openhands.sdk.skills import KeywordTrigger, PathTrigger, Skill, TaskTrigger
from openhands.sdk.skills.utils import find_skill_md

from . import third_party_skills as tps
from .config import BUILTIN_SKILLS_DIR, Config
from .model_files import user_dir
from .project_state import state_dir
from .skills import load_skill_catalog

LOCK_FILE = "skills.lock.json"
OFF_FILE = "official-off.json"

OFFICIAL = "official"
GLOBAL = "global"
PROJECT = "project"
OWN = "project's own"
THIRD_PARTY = (GLOBAL, PROJECT)
# How a notice names a third-party layer's skill.
_YOUR = {GLOBAL: "global skill", PROJECT: "project skill"}


def global_dir() -> Path:
    """Third-party skills for every project on this computer."""
    return Path(user_dir()) / "skills"


def project_dir(workspace: str | Path) -> Path:
    """Third-party skills for one project, inside its `.certo/`."""
    return Path(state_dir(str(workspace))) / "skills"


def disabled_project_skills(workspace: str | Path, projects_dir: str | Path) -> list[str]:
    """Project skills a run in `workspace` must not get. The SDK also reads
    `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules` and
    `.agents/skills/` from the root of the git repository around the
    workspace. For a project Certo generates (inside `projects_dir`) those
    are another repository's own, Certo's for a project under its
    `projects/`: it gets only what is in its folder, such as the skills
    Certo copied there. An existing folder outside `projects_dir` keeps
    them: there the repository around it is its context. The SDK keeps the
    workspace's skill over a same-named one from the repository, so a skill
    from outside has no local twin and can be turned off by name."""
    root = Path(workspace).resolve()
    if not root.is_dir() or not root.is_relative_to(Path(projects_dir).resolve()):
        return []
    return sorted({s.name for s in _project_skills(root) if not _inside(s, root)})


def _project_skills(workspace: Path) -> list[Skill]:
    from openhands.sdk.skills import load_project_skills

    return load_project_skills(workspace)


def _inside(skill: Skill, root: Path) -> bool:
    return bool(skill.source) and Path(skill.source).resolve().is_relative_to(root)


def lock_path(root: Path) -> Path:
    return root / LOCK_FILE


def official_off(root: Path) -> list[str]:
    """The official skills turned off in one third-party folder. A file
    that can't be read turns nothing off: a run never stops on it."""
    try:
        names = json.loads((root / OFF_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(names, list):
        return []
    return sorted({n for n in names if isinstance(n, str)})


def set_official_off(root: Path, name: str, off: bool) -> bool:
    """Turn the official skill `name` off (or back on) in `root`; False
    when it already was. The file goes once nothing is off."""
    names = set(official_off(root))
    if (name in names) == off:
        return False
    names = names | {name} if off else names - {name}
    path = root / OFF_FILE
    if names:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(names), indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return True


@dataclass(frozen=True)
class SkillRow:
    """One skill as found in one layer."""

    name: str
    layer: str
    where: str  # the file or folder it came from
    skill: Skill | None = None  # None when it isn't used (off, or can't load)
    state: str = "on"  # "on", or why not, e.g. "off (downloaded; run ... enable)"
    downloaded: bool = False  # from git, in the lock file
    replaced_by: str | None = None  # the layer of the skill that replaces it

    @property
    def active(self) -> bool:
        return self.skill is not None and self.replaced_by is None


@dataclass(frozen=True)
class SkillSet:
    rows: tuple[SkillRow, ...]
    # Lines a run prints: a third-party skill that replaces an official one.
    notices: tuple[str, ...]

    @property
    def skills(self) -> list[Skill]:
        """What Certo passes to the agent. The project's own skills are left
        to the SDK, which loads them from the workspace itself."""
        return [r.skill for r in self.rows if r.active and r.layer != OWN]  # type: ignore[misc]

    def without_official(self, names: Iterable[str]) -> list[Skill]:
        """`skills`, minus the official skills named in `names` (a bench
        arm's `skills_off`). A third-party skill of the same name, which
        replaces the official one, stays."""
        off = set(names)
        return [
            r.skill  # type: ignore[misc]
            for r in self.rows
            if r.active and r.layer != OWN and not (r.layer == OFFICIAL and r.name in off)
        ]


def untrusted(skill: Skill) -> Skill:
    return skill.model_copy(update={"content": tps.neutralize_inline_commands(skill.content)})


def load_one(path: Path, root: Path) -> Skill:
    """A `.md` file (named by its frontmatter, else its file name) or a
    `SKILL.md` folder (named as the AgentSkills standard says)."""
    if path.is_dir():
        skill_md = find_skill_md(path)
        if skill_md is None:
            raise tps.ThirdPartySkillError(f"{path} has no SKILL.md")
        return Skill.load(skill_md, strict=True, skip_mcp=True)
    return Skill.load(path, root)


def load_folder(root: Path, layer: str, command_scope: str) -> list[SkillRow]:
    """Every skill at the top level of one third-party folder.
    `command_scope` (`--global`, `--project NAME`) goes into the hints."""
    if not root.is_dir():
        return []
    try:
        locked = tps.read_lock(lock_path(root))
    except tps.ThirdPartySkillError as exc:
        return [SkillRow(LOCK_FILE, layer, str(lock_path(root)), state=f"can't read: {exc}")]
    rows: list[SkillRow] = []
    downloaded = {r.name: r for r in _downloaded_rows(root, layer, locked, command_scope)}
    for item in sorted(root.iterdir()):
        if item.name.startswith(".") or item.name == LOCK_FILE:
            continue
        if item.is_dir() and item.name in downloaded:
            continue
        if item.is_file() and (item.suffix != ".md" or item.name == "README.md"):
            continue
        try:
            skill = untrusted(load_one(item, root))
        except tps.SKILL_LOAD_ERRORS + (tps.ThirdPartySkillError,) as exc:
            rows.append(SkillRow(item.stem, layer, str(item), state=f"can't load: {exc}"))
            continue
        rows.append(SkillRow(skill.name, layer, str(item), skill))
    return rows + list(downloaded.values())


def _downloaded_rows(
    root: Path, layer: str, locked: dict[str, tps.LockEntry], command_scope: str
) -> list[SkillRow]:
    rows = []
    loaded = {s.name: s for s in tps.load_enabled_skills(root, lock_path(root))}
    for name, entry in sorted(locked.items()):
        where = str(root / name)
        if name in loaded:
            rows.append(SkillRow(name, layer, where, loaded[name], downloaded=True))
            continue
        status = tps.integrity_status(root / name, entry)
        if not entry.enabled:
            state = f"off (downloaded; turn it on with: certo skills enable {name} {command_scope})"
        elif status != "ok":
            state = f"off (its files are {status}; run: certo skills sync {command_scope})"
        else:
            state = "off (its license isn't acknowledged)"
        rows.append(SkillRow(name, layer, where, state=state, downloaded=True))
    return rows


def _own_rows(workspace: Path, projects_dir: str) -> list[SkillRow]:
    disabled = set(disabled_project_skills(workspace, projects_dir))
    return [
        SkillRow(s.name, OWN, s.source or str(workspace), s)
        for s in _project_skills(workspace)
        if s.name not in disabled
    ]


def collect(
    cfg: Config,
    workspace: str | Path | None,
    *,
    project_name: str | None = None,
    own: bool = True,
) -> SkillSet:
    """Every skill a run in `workspace` gets, layer by layer, with what
    replaces what. `workspace` None: no project (no project layers).
    `own` False leaves out the project's own skills, which a run doesn't
    need: the SDK loads them itself."""
    notices: list[str] = []
    global_root = Path(cfg.global_skills_dir) if cfg.global_skills_dir else global_dir()
    off = {name: "--global" for name in official_off(global_root)}
    if workspace is not None:
        scope = f"--project {project_name}" if project_name else "--project NAME"
        for name in official_off(project_dir(workspace)):
            off.setdefault(name, scope)
    official = [
        SkillRow(s.name, OFFICIAL, BUILTIN_SKILLS_DIR, s)
        if s.name not in off
        else SkillRow(
            s.name,
            OFFICIAL,
            BUILTIN_SKILLS_DIR,
            state=(
                f"off ({'for every project' if off[s.name] == '--global' else 'for this project'}; "
                f"turn it on with: certo skills enable {s.name} {off[s.name]})"
            ),
        )
        for s in official_skills()
    ]
    rows = official + load_folder(global_root, GLOBAL, "--global")
    if workspace is not None:
        scope = f"--project {project_name}" if project_name else "--project NAME"
        rows += load_folder(project_dir(workspace), PROJECT, scope)
        if own:
            rows += _own_rows(Path(workspace), cfg.projects_dir)
    rows = _mark_replaced(rows)
    for name, where in sorted(off.items()):
        notices.append(
            f"Certo: the official skill '{name}' is off "
            f"({'for every project' if where == '--global' else 'for this project'}; "
            f"certo skills enable {name} {where})."
        )
    for row in rows:
        if row.layer == OFFICIAL and row.replaced_by in THIRD_PARTY:
            notices.append(
                f"Certo: your {_YOUR[row.replaced_by]} '{row.name}' replaces the official one."
            )
    return SkillSet(tuple(rows), tuple(notices))


def official_skills() -> list[Skill]:
    return load_skill_catalog(BUILTIN_SKILLS_DIR)


def _mark_replaced(rows: Iterable[SkillRow]) -> list[SkillRow]:
    out = list(rows)
    latest: dict[str, int] = {}
    for i, row in enumerate(out):
        if row.skill is None:
            continue
        if row.name in latest:
            j = latest[row.name]
            out[j] = replace(out[j], replaced_by=row.layer)
        latest[row.name] = i
    return out


# --- How a skill fires, and what it costs -------------------------------------------

_MAX_SHOWN = 6


def _some(words: list[str]) -> str:
    shown = ", ".join(words[:_MAX_SHOWN])
    return shown + (f" and {len(words) - _MAX_SHOWN} more" if len(words) > _MAX_SHOWN else "")


def how_it_fires(skill: Skill) -> str:
    trigger = skill.trigger
    if isinstance(trigger, KeywordTrigger):
        return f"when the task says: {_some(trigger.keywords)}"
    if isinstance(trigger, TaskTrigger):
        return f"when the task says: {_some(trigger.triggers)}"
    if isinstance(trigger, PathTrigger):
        return f"when the agent touches: {_some(trigger.paths)}"
    if skill.is_agentskills_format:
        return "when the agent asks for it (its name and description are always listed)"
    return "always"


def size_in_tokens(skill: Skill) -> int:
    """A rough count (four characters a token): enough to compare skills."""
    return max(1, round(len(skill.content) / 4))


# Official skills that fit only one kind of project: left out when the
# project folder is clearly another language (verification.detect_project).
# A new, empty folder ("unknown") keeps them; their triggers do the rest.
OFFICIAL_LANGUAGES: dict[str, tuple[str, ...]] = {
    "pytest-conventions": ("python",),
}


def project_language(workspace: str | Path | None) -> str:
    """The project folder's language, or "unknown" (no folder, or none found)."""
    if workspace is None or not Path(workspace).is_dir():
        return "unknown"
    from .verification import detect_project

    try:
        return detect_project(str(workspace)).language
    except OSError:
        return "unknown"


def off_for_language(language: str) -> list[str]:
    """The official skills that don't fit a project of `language`."""
    if language in ("unknown", "ambiguous"):
        return []
    return [name for name, fits in OFFICIAL_LANGUAGES.items() if language not in fits]


def fires_for_task(skill: Skill, task: str) -> str | None:
    """Why `skill` goes into a run of `task` from its first message, or None.
    The same matching a run uses (`Skill.match_trigger`)."""
    trigger = skill.trigger
    if isinstance(trigger, KeywordTrigger | TaskTrigger):
        word = skill.match_trigger(task)
        return f'"{word}" is in the task' if word else None
    if trigger is None and not skill.is_agentskills_format:
        return "always on"
    return None


def later_for_task(skill: Skill) -> str | None:
    """How `skill` may still come in later in a run, or None."""
    if isinstance(skill.trigger, PathTrigger):
        return f"if the agent touches {_some(skill.trigger.paths)}"
    if skill.is_agentskills_format:
        return "if the agent asks for it"
    return None


def describe_dir(path: Path) -> str:
    """A folder as the user typed it, with `~` for the home folder."""
    home = os.path.expanduser("~")
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + os.sep) else text
