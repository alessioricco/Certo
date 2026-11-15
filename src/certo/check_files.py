"""Did the agent change the files the project's checks rely on?

`verified` means the project's own checks passed after the run. An agent
can make them pass by weakening them: editing a test, deleting one, or
switching a lint rule off. Certo copies the check files before the run
(test files, and the settings files that steer tests, build and lint)
and, after a `verified` run, reports each one the agent changed or
deleted, with the lines changed, removed and added, and the changed
lines themselves for the report. New files aren't reported: adding tests
is normal. An edit an acceptance check asks for (a version bump a
`file_contains` check requires) isn't reported either. Report only; the
task may have asked for it.
"""

from __future__ import annotations

import difflib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .escalation import workspace_listing

_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_TEST_FILE = re.compile(
    r"^(test_.+\.py|.+_test\.(py|go)|.+\.(test|spec)\.[cm]?[jt]sx?|conftest\.py"
    r"|.+Tests?\.(java|kt))$"
)
_SETTINGS_FILES = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "pytest.ini",
        "tox.ini",
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".mypy.ini",
        ".flake8",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Makefile",
    }
)
_SETTINGS_PREFIXES = (
    "tsconfig",
    "jest.config",
    "vitest.config",
    "eslint.config",
    ".eslintrc",
    ".golangci",
)
# Larger files are left out of the copy (a check file is rarely this big).
_MAX_FILE_BYTES = 1_000_000
_LISTED_LIMIT = 5
# Changed lines kept per file for the report, and characters per line.
_SHOWN_LINES = 12
_SHOWN_WIDTH = 160


def is_check_file(path: str) -> bool:
    """Whether `path` (relative to the project) is a test file or a file
    that steers the project's checks."""
    parts = path.replace(os.sep, "/").split("/")
    name = parts[-1]
    return (
        any(part in _TEST_DIRS for part in parts[:-1])
        or bool(_TEST_FILE.match(name))
        or name in _SETTINGS_FILES
        or name.startswith(_SETTINGS_PREFIXES)
    )


def snapshot_check_files(root: str) -> dict[str, bytes]:
    """The content of every check file under `root`, by relative path."""
    snapshot: dict[str, bytes] = {}
    for path, (size, _mtime) in workspace_listing(root).items():
        if size > _MAX_FILE_BYTES or not is_check_file(path):
            continue
        try:
            with open(os.path.join(root, path), "rb") as f:
                snapshot[path] = f.read()
        except OSError:
            continue
    return snapshot


@dataclass(frozen=True)
class CheckFileChange:
    path: str
    deleted: bool
    removed: int  # lines gone
    added: int  # new lines
    changed: int = 0  # lines rewritten in place (an extended import, say)
    # The changed lines, "- old" and "+ new", at most _SHOWN_LINES.
    lines: tuple[str, ...] = field(default=())

    @property
    def described(self) -> str:
        if self.deleted:
            return f"{self.path} (deleted)"
        counts = [
            f"{_lines(count)} {what}"
            for count, what in (
                (self.changed, "changed"),
                (self.removed, "removed"),
                (self.added, "added"),
            )
            if count
        ]
        return f"{self.path} ({', '.join(counts) or 'line endings only'})"


def _lines(count: int) -> str:
    return f"{count} line" if count == 1 else f"{count} lines"


def check_file_changes(
    root: str,
    before: dict[str, bytes],
    required: Mapping[str, Sequence[str]] | None = None,
) -> tuple[CheckFileChange, ...]:
    """Each check file in `before` that is now different or gone.
    `required`: by path, the texts the task's acceptance checks require in
    that file; a change whose every new or rewritten line holds one of
    them, and that removes nothing else, is what the task asked for and is
    left out (a user's run, 2026-11-14: a version bump an acceptance check
    required was flagged as a change to the checks)."""
    required = required or {}
    changes = []
    for path, old in sorted(before.items()):
        try:
            with open(os.path.join(root, path), "rb") as f:
                new = f.read()
        except FileNotFoundError:
            changes.append(CheckFileChange(path, True, len(old.splitlines()), 0))
            continue
        except OSError:
            continue
        if new == old:
            continue
        changed = removed = added = 0
        old_lines = old.decode("utf-8", "replace").splitlines()
        new_lines = new.decode("utf-8", "replace").splitlines()
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        shown: list[str] = []
        asked = True  # every edit is one an acceptance check requires
        texts = required.get(path.replace(os.sep, "/"), ())
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            rewritten = min(i2 - i1, j2 - j1)
            changed += rewritten
            removed += i2 - i1 - rewritten
            added += j2 - j1 - rewritten
            asked = asked and _asked_for(old_lines[i1:i2], new_lines[j1:j2], texts)
            shown += [_shown(f"- {line}") for line in old_lines[i1:i2]]
            shown += [_shown(f"+ {line}") for line in new_lines[j1:j2]]
        if asked and texts:
            continue
        if len(shown) > _SHOWN_LINES:
            shown = [*shown[:_SHOWN_LINES], f"... and {len(shown) - _SHOWN_LINES} more lines"]
        changes.append(CheckFileChange(path, False, removed, added, changed, tuple(shown)))
    return tuple(changes)


def _asked_for(gone: list[str], came: list[str], texts: Sequence[str]) -> bool:
    """Whether one edit only puts in lines an acceptance check requires:
    every new line holds a required text, and no more lines go than come."""
    return (
        bool(came)
        and len(gone) <= len(came)
        and all(any(text in line for text in texts) for line in came)
    )


def _shown(line: str) -> str:
    return line if len(line) <= _SHOWN_WIDTH else line[: _SHOWN_WIDTH - 3] + "..."


def required_texts(checks: Sequence[object] | None) -> dict[str, list[str]]:
    """By path, the texts the acceptance checks require (`file_contains`)."""
    texts: dict[str, list[str]] = {}
    for check in checks or ():
        contains = getattr(check, "contains", None)
        if getattr(check, "kind", None) == "file_contains" and contains:
            path = str(check.path).replace(os.sep, "/").removeprefix("./")
            texts.setdefault(path, []).append(contains)
    return texts


def changes_note(changes: tuple[CheckFileChange, ...]) -> str:
    """The limitation line for a `verified` run that changed check files."""
    listed = ", ".join(c.described for c in changes[:_LISTED_LIMIT])
    more = len(changes) - _LISTED_LIMIT
    if more > 0:
        listed += f", and {more} more"
    count = "1 file" if len(changes) == 1 else f"{len(changes)} files"
    return (
        f"The agent changed {count} the checks rely on: {listed}. The checks "
        "passed on the changed files; read the changes before you trust them."
    )
