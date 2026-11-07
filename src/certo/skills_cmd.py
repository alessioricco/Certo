"""`certo skills`: see, add and remove the skills a run gets.

Official skills (Certo's own) are only listed: a release changes them.
Third-party skills are added to one of two folders, never anywhere git
sees them: `--global` (`~/.config/certo/skills/`, every project) or
`--project NAME` (`<project>/.certo/skills/`). One of the two is always
required, so a skill can't land in the wrong place unnoticed. Layers and
folders: `skill_library.py`.

A file or folder is checked with the SDK's own loader before it is
copied, and its trigger and size are printed. A git source keeps the
rules of downloaded skills (`third_party_skills.py`): exact commit,
license check, off until `enable`. `assess` checks and classifies the
skills of the trusted repositories in `skill_sources.yaml`
(`skill_sources.py`, `skill_assess.py`).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import TextIO

from openhands.sdk.skills.utils import find_skill_md

from . import skill_assess as assessing
from . import skill_library as lib
from . import third_party_skills as tps
from .skill_match import Fit, suggest
from .skill_sources import EXAMPLE, SourcesError, read_sources, sources_path
from .config import ConfigError, defer_llm_check, load_config, resolve_project_dir
from .init_cmd import Cancelled, Prompter
from .project_state import ensure_state_dir
from .model_catalog import task_title


class SkillsError(Exception):
    """A user-facing failure; the message says what to do."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo skills",
        description=(
            "See, add and remove the skills a run gets. Official skills come with Certo; "
            "third-party skills are yours, for every project (--global) or one "
            "(--project NAME), and never go into git."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser(
        "list",
        help="List every skill a run gets: official and third-party, how each fires, its size.",
    )
    listing.add_argument(
        "--project",
        metavar="NAME",
        help="Also show that project's skills (in CERTO_PROJECTS_DIR; . is the current folder).",
    )
    listing.add_argument(
        "--task",
        metavar="TEXT",
        help="Show which skills would go into a run of this task, and why.",
    )

    add = sub.add_parser(
        "add",
        help="Add a skill from a file, a folder, or git (github:OWNER/REPO PATH).",
        description=(
            "Add a third-party skill. FILE_OR_FOLDER_OR_SOURCE is a .md skill file, a folder "
            "with a SKILL.md, or a git source (github:OWNER/REPO, or an https:// git URL) "
            "followed by the skill's folder in that repository. A skill from a file or folder "
            "is on at once; one from git stays off until `certo skills enable`."
        ),
    )
    add.add_argument("source", metavar="FILE_OR_FOLDER_OR_SOURCE")
    add.add_argument("path", nargs="?", help="With a git source: the skill's folder in it.")
    add.add_argument("--ref", help="With a git source: a branch, tag or commit (default: HEAD).")
    add.add_argument(
        "--yes", "-y", action="store_true", help="Replace a skill of the same name without asking."
    )
    _scope(add)

    remove = sub.add_parser("remove", help="Remove a third-party skill.")
    remove.add_argument("name")
    _scope(remove)

    enable = sub.add_parser("enable", help="Turn on a skill downloaded from git.")
    enable.add_argument("name")
    enable.add_argument(
        "--accept-unknown-license",
        action="store_true",
        help="Turn it on although its license couldn't be established (you checked it).",
    )
    _scope(enable)

    disable = sub.add_parser("disable", help="Turn off a skill downloaded from git.")
    disable.add_argument("name")
    _scope(disable)

    update = sub.add_parser(
        "update", help="Download a git skill again; a changed one is turned off for review."
    )
    update.add_argument("name")
    update.add_argument("--ref", help="A branch, tag or commit (default: the one it was added at).")
    _scope(update)

    sync = sub.add_parser(
        "sync", help="Restore git skills whose files are missing or changed, at their commit."
    )
    _scope(sync)

    assess = sub.add_parser(
        "assess",
        help="Check and classify every skill of your trusted repositories (skill_sources.yaml).",
        description=(
            "Fetch the repositories listed in skill_sources.yaml (next to the skills folder: "
            "~/.config/certo/ with --global, <project>/.certo/ with --project) and check "
            "every skill in them: license, scripts, size, how it fires, what it is for. "
            "Each gets a verdict: usable, needs review or rejected. The result is saved for "
            "later use; assessing again replaces it."
        ),
    )
    _scope(assess)

    suggest = sub.add_parser(
        "suggest",
        help="Show which assessed skills fit a project and a task, and why. Installs nothing.",
        description=(
            "Match the skills `certo skills assess` saved (yours for every project, and the "
            "project's own) against a project's files and a task, with fixed rules. Prints "
            "the skills that fit, best first, with the reasons. Installs nothing."
        ),
    )
    suggest.add_argument(
        "--project",
        metavar="NAME",
        default=".",
        help="The project to match (in CERTO_PROJECTS_DIR; default . is the current folder).",
    )
    suggest.add_argument(
        "--task", metavar="TEXT_OR_FILE", default="", help="The task: text or a file."
    )
    suggest.add_argument(
        "--limit", type=int, default=10, metavar="N", help="Show at most N skills (default 10)."
    )
    return parser


def _scope(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="Your skills for every project (~/.config/certo/skills/).",
    )
    group.add_argument(
        "--project",
        metavar="NAME",
        help="One project's skills (<project>/.certo/skills/; . is the current folder).",
    )


def skills_main(
    argv: list[str],
    *,
    prompter: Prompter | None = None,
    interactive: bool | None = None,
    out: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    prompter = prompter or Prompter(out=out)
    interactive = sys.stdin.isatty() if interactive is None else interactive
    try:
        # Skills need no model: only the folders.
        with defer_llm_check():
            cfg = load_config()
        if args.command == "list":
            return _list(cfg, args, prompter)
        if args.command == "suggest":
            return _suggest(cfg, args, prompter)
        root, scope = _folder(cfg, args)
        if args.command == "add":
            return _add(cfg, args, root, scope, prompter, interactive)
        if args.command == "remove":
            return _remove(args.name, root, scope, prompter)
        if args.command == "assess":
            return _assess(root, scope, prompter)
        return _downloaded_command(args, root, scope, prompter)
    except (SkillsError, tps.ThirdPartySkillError, ConfigError, SourcesError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Cancelled:
        prompter.say("\nCancelled; nothing changed.")
        return 130


def _project(cfg, name: str) -> Path:
    """`.` is the folder a run without --project works in (CERTO_WORKSPACE,
    by default the current folder); any other name, a project in
    CERTO_PROJECTS_DIR, as for a run."""
    if name == ".":
        return Path(cfg.workspace).resolve()
    path = Path(resolve_project_dir(cfg.projects_dir, name))
    if not path.is_dir():
        raise SkillsError(f"There is no project '{name}' in {cfg.projects_dir}.")
    return path


def _folder(cfg, args: argparse.Namespace) -> tuple[Path, str]:
    """The third-party folder a command changes, and its flag for hints."""
    if args.global_:
        return lib.global_dir(), "--global"
    return lib.project_dir(_project(cfg, args.project)), f"--project {args.project}"


# --- list ------------------------------------------------------------------------------

_HEADINGS = {
    lib.OFFICIAL: "Official skills (come with Certo; a release changes them)",
    lib.GLOBAL: "Your global skills",
    lib.PROJECT: "This project's skills",
    lib.OWN: "The project's own skills (.agents/skills/, AGENTS.md; Certo never changes them)",
}


def _list(cfg, args: argparse.Namespace, prompter: Prompter) -> int:
    workspace = _project(cfg, args.project) if args.project else None
    found = lib.collect(cfg, workspace, project_name=args.project)
    where = {
        lib.GLOBAL: lib.describe_dir(lib.global_dir()),
        lib.PROJECT: lib.describe_dir(lib.project_dir(workspace)) if workspace else "",
    }
    for layer in (lib.OFFICIAL, lib.GLOBAL, lib.PROJECT, lib.OWN):
        rows = [r for r in found.rows if r.layer == layer]
        if layer in (lib.PROJECT, lib.OWN) and workspace is None:
            continue
        if not rows and layer == lib.OWN:
            continue
        heading = _HEADINGS[layer] + (f", in {where[layer]}" if where.get(layer) else "")
        prompter.say(f"{heading}:")
        if not rows:
            prompter.say("  none")
        for row in rows:
            prompter.say(f"  {_row_line(row)}")
        prompter.say()
    if workspace is None:
        prompter.say("Add --project NAME to see a project's skills too.")
    if args.task:
        _for_task(found, args.task, prompter)
    return 0


def _row_line(row: lib.SkillRow) -> str:
    if row.skill is None:
        return f"{row.name}: {row.state}"
    parts = [
        lib.how_it_fires(row.skill),
        f"about {lib.size_in_tokens(row.skill):,} tokens",
    ]
    if row.downloaded:
        parts.append("from git")
    if row.replaced_by:
        parts.append(f"replaced by the {_LAYER_NAMES[row.replaced_by]} one")
    return f"{row.name}: " + "; ".join(parts)


_LAYER_NAMES = {
    lib.OFFICIAL: "official",
    lib.GLOBAL: "global",
    lib.PROJECT: "project",
    lib.OWN: "project's own",
}


def _for_task(found: lib.SkillSet, task: str, prompter: Prompter) -> None:
    active = [r for r in found.rows if r.active and r.skill is not None]
    now = [(r, why) for r in active if (why := lib.fires_for_task(r.skill, task))]
    later = [(r, how) for r in active if (how := lib.later_for_task(r.skill))]
    prompter.say(f"For the task {task_title(task)!r}:")
    if now:
        total = sum(lib.size_in_tokens(r.skill) for r, _ in now)
        prompter.say(f"  From its first message (about {total:,} tokens):")
        for row, why in now:
            prompter.say(f"    {row.name} ({_LAYER_NAMES[row.layer]}): {why}")
    else:
        prompter.say("  No skill goes in from its first message.")
    if later:
        prompter.say("  Later, maybe:")
        for row, how in later:
            prompter.say(f"    {row.name} ({_LAYER_NAMES[row.layer]}): {how}")


# --- add / remove ----------------------------------------------------------------------


def _add(
    cfg,
    args: argparse.Namespace,
    root: Path,
    scope: str,
    prompter: Prompter,
    interactive: bool,
) -> int:
    source = Path(args.source).expanduser()
    if source.exists():
        if args.path or args.ref:
            raise SkillsError("A path in a repository and --ref go with a git source only.")
        return _add_local(source, root, scope, args.yes, prompter, interactive)
    if not args.path:
        raise SkillsError(
            f"{args.source} isn't a file or folder here. For a skill in a git repository, "
            "give the repository and the skill's folder in it, for example: "
            f"certo skills add github:OWNER/REPO skills/NAME {scope}"
        )
    return _add_from_git(args, root, scope, prompter)


def _add_local(
    source: Path, root: Path, scope: str, yes: bool, prompter: Prompter, interactive: bool
) -> int:
    if source.is_file() and source.suffix != ".md":
        raise SkillsError(f"{source} isn't a skill: a skill file ends in .md.")
    if source.is_dir() and find_skill_md(source) is None:
        raise SkillsError(
            f"{source} has no SKILL.md. Add a folder that has one, or a single .md skill file."
        )
    try:
        skill = lib.load_one(source, source.parent)
    except tps.SKILL_LOAD_ERRORS as exc:
        raise SkillsError(f"{source} isn't a skill Certo can load: {exc}") from exc
    name = skill.name
    try:
        tps.check_name(name)
    except tps.ThirdPartySkillError as exc:
        raise SkillsError(f"Its name, {name!r}, can't be a file name: {exc}") from exc
    dest = root / (name if source.is_dir() else f"{name}.md")
    existing = _existing(root, name)
    if existing:
        if not yes:
            if not interactive:
                raise SkillsError(
                    f"{lib.describe_dir(root)} already has a skill named '{name}'. "
                    "Add --yes to replace it."
                )
            if not prompter.confirm(f"Replace the skill '{name}' in {lib.describe_dir(root)}?"):
                prompter.say("Nothing changed.")
                return 0
        _delete(root, name, existing)
    if scope.startswith("--project"):
        ensure_state_dir(str(root.parent.parent))
    root.mkdir(parents=True, exist_ok=True)
    skipped = tps.copy_regular_files(source, dest) if source.is_dir() else []
    if not source.is_dir():
        shutil.copyfile(source, dest)
    added = lib.untrusted(lib.load_one(dest, root))
    prompter.say(f"Added '{name}' to {lib.describe_dir(root)}. It is on.")
    if skipped:
        prompter.say(f"  Skipped links inside it: {', '.join(skipped)}.")
    prompter.say(f"  Fires {lib.how_it_fires(added)}; about {lib.size_in_tokens(added):,} tokens.")
    if any(s.name == name for s in lib.official_skills()):
        prompter.say(
            f"  It replaces the official skill '{name}'; a run says so. Remove it with: "
            f"certo skills remove {name} {scope}"
        )
    return 0


def _add_from_git(args: argparse.Namespace, root: Path, scope: str, prompter: Prompter) -> int:
    if scope.startswith("--project"):
        ensure_state_dir(str(root.parent.parent))
    result = tps.install(
        args.source, args.path, ref=args.ref, install_dir=root, lock_path=lib.lock_path(root)
    )
    entry = result.entry
    prompter.say(f"Downloaded '{result.name}' to {lib.describe_dir(root)}. It is off.")
    prompter.say(f"  From {entry.source_url}")
    license_line = entry.license if entry.license_established else "not established"
    prompter.say(
        f"  License: {license_line}" + (f" ({entry.license_url})" if entry.license_url else "")
    )
    for note in entry.license_notes:
        prompter.say(f"  Note: {note}")
    for warning in result.warnings:
        prompter.say(f"  Warning: {warning}")
    prompter.say(
        f"Read its files and its license, then turn it on with: "
        f"certo skills enable {result.name} {scope}"
    )
    prompter.say(
        "The license is recognised from its text, which isn't legal advice; downloading a "
        "skill doesn't by itself give you the right to use it."
    )
    return 0


def _existing(root: Path, name: str) -> str | None:
    """What holds a skill called `name` in `root`: "downloaded", "folder",
    "file", or None."""
    if not root.is_dir():
        return None
    if name in tps.read_lock(lib.lock_path(root)):
        return "downloaded"
    if (root / name).is_dir():
        return "folder"
    if (root / f"{name}.md").is_file():
        return "file"
    for item in root.glob("*.md"):
        try:
            if lib.load_one(item, root).name == name:
                return "file"
        except tps.SKILL_LOAD_ERRORS:
            continue
    return None


def _delete(root: Path, name: str, kind: str) -> None:
    if kind == "downloaded":
        tps.remove(name, install_dir=root, lock_path=lib.lock_path(root))
    elif kind == "folder":
        shutil.rmtree(root / name)
    else:
        target = root / f"{name}.md"
        if not target.is_file():
            target = next(p for p in root.glob("*.md") if lib.load_one(p, root).name == name)
        target.unlink()


def _remove(name: str, root: Path, scope: str, prompter: Prompter) -> int:
    kind = _existing(root, name)
    if kind is None:
        if any(s.name == name for s in lib.official_skills()):
            raise SkillsError(
                f"'{name}' is an official skill; it comes with Certo and can't be removed."
            )
        raise SkillsError(
            f"There is no skill named '{name}' in {lib.describe_dir(root)}. "
            f"See them with: certo skills list"
            + (f" {scope}" if scope.startswith("--project") else "")
        )
    _delete(root, name, kind)
    prompter.say(f"Removed '{name}' from {lib.describe_dir(root)}.")
    return 0


# --- downloaded skills: enable, disable, update, sync ---------------------------------------


def _downloaded_command(
    args: argparse.Namespace, root: Path, scope: str, prompter: Prompter
) -> int:
    paths = {"install_dir": root, "lock_path": lib.lock_path(root)}
    if args.command == "sync":
        results = tps.sync(**paths)
        if not results:
            prompter.say(f"No skill downloaded from git in {lib.describe_dir(root)}.")
        for name, status in results:
            prompter.say(f"{name}: {status}")
        return 0 if all(status in ("ok", "restored") for _, status in results) else 1
    if args.name not in tps.read_lock(paths["lock_path"]) and _existing(root, args.name):
        raise SkillsError(
            f"'{args.name}' was added from a file or folder, so it is always on. "
            f"To stop using it: certo skills remove {args.name} {scope}"
        )
    if args.command == "enable":
        tps.set_enabled(
            args.name, True, accept_unknown_license=args.accept_unknown_license, **paths
        )
        prompter.say(f"'{args.name}' is on: runs pass its instructions to the agent.")
    elif args.command == "disable":
        tps.set_enabled(args.name, False, **paths)
        prompter.say(f"'{args.name}' is off.")
    else:
        entry, review = tps.update(args.name, ref=args.ref, **paths)
        prompter.say(f"'{args.name}' is now at commit {entry.revision[:12]}.")
        if review:
            prompter.say(
                "Its content or license changed, so it was turned off. Read it, then: "
                f"certo skills enable {args.name} {scope}"
            )
    return 0


# --- assess: trusted repositories -------------------------------------------------------------


def _assess(root: Path, scope: str, prompter: Prompter) -> int:
    path = sources_path(root)
    sources = read_sources(path)
    if not sources:
        raise SkillsError(
            f"No trusted repositories: {path} lists none. Create it, for example:\n\n"
            f"{EXAMPLE}\nthen run: certo skills assess {scope}"
        )
    if scope.startswith("--project"):
        ensure_state_dir(str(root.parent.parent))
    prompter.say(
        f"Assessing {len(sources)} trusted repositor{'y' if len(sources) == 1 else 'ies'}..."
    )
    result = assessing.assess(root, sources, reserved=[s.name for s in lib.official_skills()])
    failed = False
    for source_result in result.results:
        prompter.say()
        label = source_result.source.label
        if source_result.error:
            failed = True
            prompter.say(f"{label}: not assessed. {source_result.error}")
            continue
        skills = source_result.skills
        counts = ", ".join(
            f"{sum(1 for s in skills if s.verdict == v)} {v}" for v in assessing.VERDICTS
        )
        prompter.say(f"{label} at {source_result.revision[:12]}: {len(skills)} skills ({counts}).")
        for verdict in assessing.VERDICTS:
            group = [s for s in skills if s.verdict == verdict]
            if group:
                prompter.say(f"  {verdict.capitalize()}:")
            for skill in group:
                prompter.say(f"    {_assessed_line(skill)}")
    prompter.say()
    prompter.say(
        f"Saved in {lib.describe_dir(assessing.trusted_dir(root))}: "
        f"{result.count(assessing.USABLE)} usable, "
        f"{result.count(assessing.NEEDS_REVIEW)} to review, "
        f"{result.count(assessing.REJECTED)} rejected. Runs don't use them yet."
    )
    return 1 if failed else 0


def _assessed_line(skill: assessing.Assessed) -> str:
    if skill.verdict == assessing.REJECTED:
        return f"{skill.name}: {'; '.join(skill.reasons)}"
    what = ", ".join(skill.steps + skill.ecosystems) or "general"
    line = f"{skill.name} ({what}): fires {skill.fires}; about {skill.tokens:,} tokens"
    if skill.reasons:
        line += ". Review: " + "; ".join(skill.reasons)
    return line


# --- suggest: match assessed skills to a project ------------------------------------------------


def _suggest(cfg, args: argparse.Namespace, prompter: Prompter) -> int:
    workspace = _project(cfg, args.project)
    task = args.task
    if task and Path(task).is_file():
        task = Path(task).read_text(encoding="utf-8")
    scopes = [("global", lib.global_dir()), ("project", lib.project_dir(workspace))]
    found = suggest(scopes, workspace, task)
    if found.indexed == 0:
        raise SkillsError(
            "No assessed skills yet. List the repositories you trust in "
            "skill_sources.yaml, then run: certo skills assess --global"
        )
    what = ", ".join(found.project_ecosystems) or "no known ecosystem"
    steps = ", ".join(found.task_steps) or "none named"
    prompter.say(f"Project {workspace} ({what}); steps in the task: {steps}.")
    if not found.fits:
        prompter.say(
            "No usable skill fits this project and task."
            if task
            else "No usable skill fits this project. Give --task to match a task too."
        )
    else:
        prompter.say("Usable skills that fit, best first:")
        for fit in found.fits[: args.limit]:
            prompter.say(f"  {_fit_line(fit)}")
        if len(found.fits) > args.limit:
            prompter.say(f"  ... and {len(found.fits) - args.limit} more (--limit).")
    if found.after_review:
        prompter.say("Would fit once reviewed:")
        for fit in found.after_review[: args.limit]:
            reasons = "; ".join(fit.entry.reasons)
            prompter.say(f"  {fit.entry.name}: {', '.join(fit.reasons)}. Review: {reasons}")
    prompter.say("Runs don't load these skills yet.")
    return 0


def _fit_line(fit: Fit) -> str:
    entry = fit.entry
    if fit.fires_alone:
        how = "it fires on its own"
    elif entry.fires_kind == "on request":
        how = "the agent would see it listed and may ask for it"
    else:
        how = f"it fires {entry.fires}"
    return (
        f"{entry.name} ({fit.scope}, about {entry.tokens:,} tokens): "
        f"{', '.join(fit.reasons)}; {how}"
    )
