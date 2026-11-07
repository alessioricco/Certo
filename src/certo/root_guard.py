"""Keep the agent inside its project root (local execution).

A conversation callback that sees every action before it runs (the SDK
emits the `ActionEvent` first, then executes the batch) and blocks one
that reaches outside the root, with `conversation.state.block_action`:
the agent gets a rejection with the reason instead of the result
(ARCHITECTURE.md, "Root guard"). Docker needs none: the container only
has the project.

What counts as outside:
- a tool's `path` argument (file editor, run_tests and others) that
  resolves outside the root; the file editor may still read the allowed
  system and tool folders below, but never write there;
- in a terminal command, a word that is a path outside the root: an
  absolute path, `~`, `$HOME`, or a relative path with `..` resolved from
  the terminal's current folder; and `cd` alone (the home folder).

A guard rail, not a sandbox: a command can still reach elsewhere in ways
no word shows (a script, a variable built at run time). Docker is the
sandbox. Words with spaces (code passed with `-c`/`-e`) are not read as
paths, and an absolute word whose first folder doesn't exist (`/api/v1`,
a regex) isn't a path either.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from typing import Any

from openhands.sdk.event import ActionEvent, ObservationEvent

# Outside the root, but what commands and tools use on their own: system
# folders and temporary files.
_SYSTEM_DIRS = (
    "/bin",
    "/sbin",
    "/usr",
    "/opt",
    "/etc",
    "/dev",
    "/proc",
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
    "/private/etc",
    "/System",
    "/Library/Developer",
)
# Folders in the home folder where tools keep their installs and caches.
_HOME_TOOL_DIRS = (
    ".cache",
    ".npm",
    ".nvm",
    ".volta",
    ".yarn",
    ".pnpm-store",
    ".bun",
    ".deno",
    ".local",
    ".cargo",
    ".rustup",
    "go",
    ".pyenv",
    ".gradle",
    ".m2",
    ".sdkman",
    "Library/Caches",
    "Library/pnpm",
)
_SEPARATORS = {";", "&&", "||", "|", "&"}
_REDIRECT = re.compile(r"^\d*[<>]+&?")


_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def without_heredoc_bodies(command: str) -> str:
    """`command` without the lines of its here-documents (`cat > f <<'EOF'`
    ... `EOF`): they are a file's content, not words of the command. Read as
    words, a Go comment (`// Package api`) was the path `/`: 8 of the 11
    actions blocked in the 0.2.3 cloud benchmark."""
    kept: list[str] = []
    waiting: list[tuple[str, bool]] = []  # (delimiter, tabs allowed before it)
    for line in command.split("\n"):
        if waiting:
            delimiter, dash = waiting[0]
            if (line.lstrip("\t") if dash else line) == delimiter:
                waiting.pop(0)
            continue
        kept.append(line)
        waiting = [(m.group(3), m.group(1) == "-") for m in _HEREDOC.finditer(line)]
    return "\n".join(kept)


def _inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # different drives on Windows
        return False


class RootGuard:
    """A conversation callback; set `conversation` once it exists."""

    def __init__(self, root: str, emit: Callable[[str], None] | None = None) -> None:
        self.root = os.path.realpath(root)
        self.cwd = self.root
        self.home = os.path.realpath(os.path.expanduser("~"))
        self.conversation: Any = None
        self.emit = emit
        self.blocked: list[str] = []

    # --- the callback ----------------------------------------------------

    def __call__(self, event: Any) -> None:
        if isinstance(event, ObservationEvent):
            working_dir = getattr(getattr(event.observation, "metadata", None), "working_dir", None)
            if isinstance(working_dir, str) and working_dir:
                self.cwd = os.path.realpath(working_dir)
            return
        if not isinstance(event, ActionEvent) or event.action is None:
            return
        reason = self.check(event.action)
        if reason is None or self.conversation is None:
            return
        self.conversation.state.block_action(event.id, reason)
        self.blocked.append(reason)
        if self.emit is not None:
            self.emit(f"Certo blocked an action outside the project root: {reason}")

    # --- the rules -------------------------------------------------------

    def check(self, action: Any) -> str | None:
        """Why `action` is outside the root, or None when it may run."""
        data = action.model_dump()
        if type(action).__name__ == "TerminalAction":
            if data.get("is_input"):
                return None  # input to a running program, not a command
            return self.check_command(str(data.get("command") or ""))
        writes = type(action).__name__ == "FileEditorAction" and data.get("command") != "view"
        for key in ("path", "paths", "directory", "file_path"):
            values = data.get(key)
            for value in values if isinstance(values, list) else [values]:
                if isinstance(value, str) and value.strip():
                    outside = self._outside(value.strip(), base=self.root, allow_tools=not writes)
                    if outside:
                        return self._reason(outside)
        return None

    def check_command(self, command: str) -> str | None:
        command = without_heredoc_bodies(command)
        # punctuation_chars: `;`, `&&`, `|` and redirections are words of
        # their own, so `cd;` is `cd` then `;`.
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:  # unbalanced quotes
            words = command.split()
        for index, word in enumerate(words):
            if word == "cd":
                following = words[index + 1] if index + 1 < len(words) else None
                if following is None or following in _SEPARATORS:
                    return self._reason(self.home)
            for candidate in self._path_words(word):
                outside = self._outside(candidate, base=self.cwd, allow_tools=True)
                if outside:
                    return self._reason(outside)
        return None

    def _path_words(self, word: str) -> list[str]:
        """The parts of one command word that may be paths."""
        if any(c.isspace() for c in word):
            return []  # code or text passed as one argument
        word = _REDIRECT.sub("", word)
        parts = [word]
        if "=" in word:
            parts = [p for value in word.split("=", 1)[1:] for p in value.split(":")]
        found = []
        for part in parts:
            if part.startswith(("/", "~", "$HOME", "${HOME}")) or part == "..":
                found.append(part)
            elif part.startswith("../") or "/../" in part or part.endswith("/.."):
                found.append(part)
        return found

    def _outside(self, value: str, *, base: str, allow_tools: bool) -> str | None:
        """The resolved path when `value` is outside the root, else None."""
        value = re.sub(r"^\$\{?HOME\}?", "~", value)
        expanded = os.path.expanduser(value)
        if os.path.isabs(expanded):
            first = expanded.lstrip("/").split("/", 1)[0]
            if value.startswith("/") and first and not os.path.exists("/" + first):
                return None  # not a path: `/api/v1`, a regex
            path = os.path.realpath(expanded)
        else:
            path = os.path.realpath(os.path.join(base, expanded))
        if _inside(path, self.root):
            return None
        # The root's neighbours and the folders above it are never system
        # or tool folders, even when the project itself is in one (/tmp).
        near = _inside(self.root, path) or _inside(path, os.path.dirname(self.root))
        if allow_tools and not near and self._tool_path(path):
            return None
        return path

    def _tool_path(self, path: str) -> bool:
        if any(_inside(path, d) for d in _SYSTEM_DIRS):
            return True
        return any(_inside(path, os.path.join(self.home, d)) for d in _HOME_TOOL_DIRS)

    def _reason(self, path: str) -> str:
        return (
            f"{path} is outside the project root {self.root}. Work only inside the "
            "project root: nothing outside it is part of the task."
        )
