"""`certo skills assess`: check and classify every skill of the trusted
repositories (`skill_sources.py`) once, for later use.

For each source: fetch it at an exact commit (the SDK's git fetch, the
cache `certo skills add` uses), find every folder with a `SKILL.md`, and
check each one with the same rules as `certo skills add` from git
(`third_party_skills.stage_fetched`: strict load, name, license, links
skipped, hash). Then, by rules only (no model call, DECISIONS.md):

- **classify** it: the lifecycle steps and ecosystems its name,
  description and trigger paths name, and how it fires;
- give a **verdict**: `usable` (a run may use it with no `enable`),
  `needs review` (the reasons say why: an unknown license, scripts it may
  ask the agent to run, inline commands, an MCP config, a large size,
  firing on every run), or `rejected` (it can't be loaded, or its name is
  taken).

The checked files of usable and needs-review skills are kept, with their
hash, in the scope's skills folder under `.trusted/` (a dot folder, so the
skill layers never load it as a skill), next to `index.json`. A run reads
the index, never the repositories; `assess` again replaces both.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openhands.sdk.skills import KeywordTrigger, PathTrigger, Skill, TaskTrigger
from openhands.sdk.skills.utils import find_skill_md

from . import skill_library as lib
from . import third_party_skills as tps
from .skill_sources import Source

TRUSTED_DIR = ".trusted"
INDEX_FILE = "index.json"
INDEX_VERSION = 1

USABLE = "usable"
NEEDS_REVIEW = "needs review"
REJECTED = "rejected"
VERDICTS = (USABLE, NEEDS_REVIEW, REJECTED)

# A skill this large costs a small model too much context to use without
# a look first (about 4,200 tokens is typical for OpenHands' own).
MAX_TOKENS = 8000

# Lifecycle steps and ecosystems, and the words in a skill's name and
# description that name each. A word matches whole; one ending in `*` is a
# stem (`refactor*` matches "refactoring").
_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("planning", ("plan*", "spec", "specs", "specification*", "requirement*", "architect*")),
    (
        "setup",
        ("setup", "set up", "install*", "environment*", "scaffold*", "bootstrap*", "dependenc*"),
    ),
    ("testing", ("test*", "qa", "coverage", "pytest", "jest", "vitest", "e2e")),
    ("debugging", ("debug*", "bug*", "troubleshoot*", "failure*", "error*")),
    ("review", ("review*", "audit*", "lint*", "code quality")),
    ("refactoring", ("refactor*", "simplif*", "clean up", "cleanup", "moderniz*", "migrat*")),
    ("security", ("security", "vulnerab*", "secret*", "cve", "owasp")),
    (
        "documentation",
        ("doc", "docs", "documentation", "documenting", "readme*", "adr", "changelog*"),
    ),
    ("git", ("git", "commit*", "pull request*", "branch*", "merge*", "rebase")),
    ("release", ("release*", "deploy*", "ci", "ci/cd", "pipeline*", "ship*")),
    (
        "integration",
        (
            "github",
            "gitlab",
            "bitbucket",
            "jira",
            "linear",
            "slack",
            "notion",
            "datadog",
            "sentry",
            "kubernetes",
            "aws",
            "azure",
            "gcp",
            "vercel",
            "netlify",
            "stripe",
        ),
    ),
)
_ECOSYSTEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("python", "pytest", "django", "flask", "fastapi", "pip", "poetry", "pyproject")),
    (
        "node",
        (
            "node",
            "node.js",
            "npm",
            "javascript",
            "typescript",
            "react",
            "vite",
            "next.js",
            "jest",
            "eslint",
        ),
    ),
    ("go", ("golang", "go.mod")),
    ("rust", ("rust", "cargo")),
    ("java", ("java", "maven", "gradle", "spring", "kotlin")),
    ("web", ("html", "css", "frontend", "browser")),
)
_PATH_ECOSYSTEMS = (
    ("python", ("*.py", "pyproject.toml", "requirements")),
    ("node", ("package.json", "*.js", "*.ts", "*.tsx")),
    ("go", ("go.mod", "*.go")),
    ("rust", ("cargo.toml", "*.rs")),
    ("java", ("pom.xml", "build.gradle", "*.java")),
)


@dataclass
class Assessed:
    """One skill in the index."""

    name: str
    repo: str
    path: str  # its folder in the repository
    verdict: str
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    ecosystems: list[str] = field(default_factory=list)
    fires: str = ""
    fires_kind: str = ""  # keywords | slash command | paths | on request | always
    tokens: int = 0
    license: str = tps.UNKNOWN_LICENSE
    revision: str = ""
    integrity: str | None = None
    folder: str | None = None  # its checked copy, relative to the .trusted folder
    source_url: str = ""


@dataclass
class SourceResult:
    source: Source
    revision: str | None
    skills: list[Assessed]
    error: str | None = None


@dataclass
class Assessment:
    results: list[SourceResult]
    index: Path

    def count(self, verdict: str) -> int:
        return sum(1 for r in self.results for s in r.skills if s.verdict == verdict)


def trusted_dir(skills_dir: Path) -> Path:
    return skills_dir / TRUSTED_DIR


def index_path(skills_dir: Path) -> Path:
    return trusted_dir(skills_dir) / INDEX_FILE


# --- classification (rules only) -------------------------------------------------------


def _mentions(text: str, words: Iterable[str]) -> bool:
    for word in words:
        stem = word.endswith("*")
        pattern = r"(?<![a-z0-9])" + re.escape(word.rstrip("*")) + ("" if stem else r"(?![a-z0-9])")
        if re.search(pattern, text):
            return True
    return False


def classify(skill: Skill) -> tuple[list[str], list[str], str, str]:
    """`(steps, ecosystems, fires, fires_kind)` for a loaded skill."""
    text = f"{skill.name.replace('-', ' ')} {skill.description or ''}".lower()
    steps = [step for step, words in _STEPS if _mentions(text, words)]
    ecosystems = [eco for eco, words in _ECOSYSTEMS if _mentions(text, words)]
    trigger = skill.trigger
    if isinstance(trigger, PathTrigger):
        globs = " ".join(trigger.paths).lower()
        ecosystems += [
            eco
            for eco, names in _PATH_ECOSYSTEMS
            if eco not in ecosystems and any(n in globs for n in names)
        ]
    if isinstance(trigger, KeywordTrigger | TaskTrigger):
        words = trigger.keywords if isinstance(trigger, KeywordTrigger) else trigger.triggers
        kind = "slash command" if words and all(w.startswith("/") for w in words) else "keywords"
    elif isinstance(trigger, PathTrigger):
        kind = "paths"
    elif skill.is_agentskills_format:
        kind = "on request"
    else:
        kind = "always"
    return steps, ecosystems, lib.how_it_fires(skill), kind


def _review_reasons(skill: Skill, staged: Path, entry: tps.LockEntry, kind: str) -> list[str]:
    reasons = []
    if not entry.license_established:
        reasons.append("its license couldn't be established")
    if any((staged / d).is_dir() for d in ("scripts", "bin")):
        reasons.append("it ships scripts its instructions may ask the agent to run")
    if re.search(r"(?<!\\)!`", skill.content):
        reasons.append("it has inline !`command` lines (shown as text, never run)")
    if (staged / ".mcp.json").exists():
        reasons.append("it ships an MCP server config (ignored)")
    tokens = lib.size_in_tokens(skill)
    if tokens > MAX_TOKENS:
        reasons.append(f"it is large: about {tokens:,} tokens (limit {MAX_TOKENS:,})")
    if kind == "always":
        reasons.append("it has no trigger, so it would go into every run")
    return reasons


# --- finding and checking ----------------------------------------------------------------


def skill_folders(checkout: Path, source: Source) -> tuple[list[str], list[str]]:
    """The repository paths of the source's skill folders, and the names in
    its `skills:` list that weren't found."""
    base = checkout / source.path if source.path else checkout
    if not base.is_dir():
        return [], list(source.skills or [])
    folders = []
    for skill_md in sorted(base.rglob("SKILL.md")):
        relative = skill_md.parent.relative_to(checkout)
        if any(part.startswith(".") for part in relative.parts) or skill_md.is_symlink():
            continue
        folders.append(relative.as_posix())
    if source.skills is None:
        return folders, []
    wanted = set(source.skills)
    kept = [f for f in folders if f.rsplit("/", 1)[-1] in wanted]
    missing = sorted(wanted - {f.rsplit("/", 1)[-1] for f in kept})
    return kept, missing


def _assess_one(
    checkout: Path,
    source: Source,
    folder: str,
    revision: str,
    staging: Path,
    reserved: set[str],
) -> tuple[Assessed, Path | None]:
    base = Assessed(name=folder.rsplit("/", 1)[-1], repo=source.repo, path=folder, verdict=REJECTED)
    base.revision = revision
    try:
        staged = tps.stage_fetched(
            checkout / folder,
            source.clone_url,
            source.web_base,
            folder,
            source.ref,
            revision,
            staging,
        )
    except tps.ThirdPartySkillError as exc:
        base.reasons = [str(exc)]
        return base, None
    skill = Skill.load(find_skill_md(staged.dir), strict=True, skip_mcp=True)
    steps, ecosystems, fires, kind = classify(skill)
    entry = staged.entry
    found = Assessed(
        name=staged.name,
        repo=source.repo,
        path=folder,
        verdict=USABLE,
        notes=[w for w in staged.warnings if w.startswith("Skipped links")] + entry.license_notes,
        steps=steps,
        ecosystems=ecosystems,
        fires=fires,
        fires_kind=kind,
        tokens=lib.size_in_tokens(skill),
        license=entry.license,
        revision=revision,
        integrity=entry.integrity,
        source_url=entry.source_url,
    )
    if staged.name in reserved:
        found.verdict = REJECTED
        found.reasons = ["an official skill has the same name"]
        return found, None
    found.reasons = _review_reasons(skill, staged.dir, entry, kind)
    if found.reasons:
        found.verdict = NEEDS_REVIEW
    return found, staged.dir


def _source_key(source: Source) -> str:
    """A folder name for one source's checked copies."""
    raw = source.clone_url.removeprefix("https://").removesuffix(".git")
    if source.path:
        raw += "/" + source.path
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")


def assess(skills_dir: Path, sources: list[Source], reserved: Iterable[str] = ()) -> Assessment:
    """Assess every source and replace the scope's `.trusted/` folder and
    index. A source that can't be fetched is reported, with no skills."""
    reserved = set(reserved)
    skills_dir.mkdir(parents=True, exist_ok=True)
    results: list[SourceResult] = []
    taken: dict[str, str] = {}
    with tempfile.TemporaryDirectory(dir=skills_dir, prefix=".assess-") as tmp:
        new_trusted = Path(tmp) / "trusted"
        new_trusted.mkdir()
        for source in sources:
            try:
                checkout, revision = tps.fetch_checkout(
                    source.clone_url, source.ref, skills_dir / ".cache"
                )
            except tps.ThirdPartySkillError as exc:
                results.append(SourceResult(source, None, [], error=str(exc)))
                continue
            folders, missing = skill_folders(checkout, source)
            skills: list[Assessed] = []
            key = _source_key(source)
            for number, folder in enumerate(folders):
                staging = Path(tmp) / "staging" / str(len(results)) / str(number)
                staging.mkdir(parents=True)
                found, files = _assess_one(checkout, source, folder, revision, staging, reserved)
                if found.verdict != REJECTED and found.name in taken:
                    found.verdict = REJECTED
                    found.reasons = [f"a skill from {taken[found.name]} has the same name"]
                    files = None
                if files is not None:
                    found.folder = f"{key}/{found.name}"
                    shutil.move(str(files), str(new_trusted / found.folder))
                    taken[found.name] = source.label
                skills.append(found)
            skills += [
                Assessed(
                    name=name,
                    repo=source.repo,
                    path=name,
                    verdict=REJECTED,
                    reasons=["listed in `skills:` but not found"],
                    revision=revision,
                )
                for name in missing
            ]
            results.append(SourceResult(source, revision, skills))
        _write_index(new_trusted, results)
        old = trusted_dir(skills_dir)
        if old.exists():
            shutil.rmtree(old)
        shutil.move(str(new_trusted), str(old))
    return Assessment(results, index_path(skills_dir))


def _write_index(folder: Path, results: list[SourceResult]) -> None:
    data = {
        "version": INDEX_VERSION,
        "assessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": [
            {
                "repo": r.source.repo,
                "ref": r.source.ref,
                "path": r.source.path,
                "revision": r.revision,
                "error": r.error,
            }
            for r in results
        ],
        "skills": [asdict(s) for r in results for s in r.skills],
    }
    (folder / INDEX_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_index(skills_dir: Path) -> list[Assessed]:
    """The scope's assessed skills; [] before the first `assess`."""
    path = index_path(skills_dir)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != INDEX_VERSION:
        return []
    return [Assessed(**item) for item in data.get("skills", [])]
