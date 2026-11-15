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

Deletes get two more rules, wherever the target is: a delete (`rm`,
`rmdir`, `unlink`, `find ... -delete` or `-exec rm`) whose target is only
known when it runs (`$(...)`, backticks, a variable) is blocked, and so is
deleting a folder that holds more than the project: the root itself or a
folder above it, the home folder, a system or tool folder itself, or the
system's temporary folder. Deleting inside them (`rm -rf /tmp/x`) is
allowed. Found in the 0.2.3 wrap-up benchmark: an agent cleaning up a demo
file ran `rm -rf "$(python -c '...print(tempfile.gettempdir())')"` and
deleted the user's whole temporary folder, with every benchmark project in
it.

A guard rail, not a sandbox: a command can still reach elsewhere in ways
no word shows (a script, a path piped to `xargs`). Docker is the
sandbox. Words with spaces (code passed with `-c`/`-e`) are not read as
paths, and an absolute word whose first folder doesn't exist (`/api/v1`,
a regex) isn't a path either.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
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
    # macOS apps: a browser to check a web page (Chromium, Chrome).
    "/Applications",
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
# Commands that delete their arguments, and words that may come before a
# command without being it.
_DELETERS = {"rm", "rmdir", "unlink"}
_PREFIXES = {"sudo", "command", "env", "nice", "nohup", "time", "exec", "builtin"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
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


_DELETE_REASON = "a delete"
_FRESH = object()
_DIRNAME = re.compile(r"\$\(dirname\s+(\S+)\)")
_VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_ASSIGNMENTS = re.compile(
    r"(?:^|[\s;&|(])(?:export\s+|local\s+|declare\s+|readonly\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)="
    r"(\"(?:[^\"\\]|\\.)*\"|'[^']*'|\$\([^)]*\)|`[^`]*`|[^\s;&|)]*)"
)


def _commands(words: list[str]):
    """(command name, its words) for each simple command in `words`."""
    start = True
    name = ""
    args: list[str] = []
    for word in words + [";"]:
        if word in _SEPARATORS or word.strip("\n;") == "" or word in (")", "{", "}"):
            if name:
                yield name, args
            start, name, args = True, "", []
            continue
        if start:
            if word == "(" or _ASSIGNMENT.match(word) or word in _PREFIXES:
                continue
            name, start = os.path.basename(word), False
            continue
        args.append(word)


def _find_deletes(args: list[str]) -> bool:
    if "-delete" in args:
        return True
    for i, arg in enumerate(args[:-1]):
        if arg in ("-exec", "-execdir", "-ok") and os.path.basename(args[i + 1]) in _DELETERS:
            return True
    return False


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
        # Variables the agent's terminal has set: name -> its value, _FRESH
        # (a `mktemp` folder), or None (only known when it runs).
        self.variables: dict[str, str | object | None] = {}

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
            what = (
                "a delete"
                if reason.startswith(_DELETE_REASON)
                else "an action outside the project root"
            )
            self.emit(f"Certo blocked {what}: {reason}")

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
        problem = self._delete_problem(command)
        if problem:
            return problem
        # punctuation_chars: `;`, `&&`, `|` and redirections are words of
        # their own, so `cd;` is `cd` then `;`.
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:  # unbalanced quotes
            words = command.split()
        # The folder the command is in, word by word: `cd sub && ... && cd ..`
        # comes back to the root, not above it (0.2.3 cloud benchmark, run 2).
        # None after `cd` to a place no word shows (`cd "$D"`): relative paths
        # are then not judged, absolute ones still are.
        here: str | None = self.cwd
        skip = -1
        for index, word in enumerate(words):
            if index == skip:
                continue
            if word == "cd":
                following = words[index + 1] if index + 1 < len(words) else None
                if following is None or following in _SEPARATORS or following == "~":
                    return self._reason(self.home)
                skip = index + 1
                target = self._resolve(following, here)
                if target is None:
                    here = None
                    continue
                outside = self._outside(following, base=here or self.root, allow_tools=True)
                if outside:
                    return self._reason(outside)
                here = target
                continue
            for candidate in self._path_words(word):
                if here is None and not candidate.startswith(("/", "~", "$HOME", "${HOME}")):
                    continue
                outside = self._outside(candidate, base=here or self.root, allow_tools=True)
                if outside:
                    return self._reason(outside)
        return None

    # --- deletes -----------------------------------------------------------

    def _delete_problem(self, command: str) -> str | None:
        """Why a delete in `command` must not run, or None. Command by
        command: the words after `rm` (or `find`'s starting
        folders when it deletes) up to the next `;`, `&&`, `|`..."""
        self._learn_variables(command)
        # One lexer for the whole command: a quoted argument can span lines
        # (`python -c "..."`); a newline outside quotes ends a command.
        lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:  # unbalanced quotes
            words = command.replace("\n", " ; ").split()
        for name, args in _commands(words):
            if name in _DELETERS:
                targets = [a for a in args if not a.startswith("-") or a == "-"]
                unknown = any(w in ("$", "(", "`") for w in args)
                whole = True
            elif name == "find" and _find_deletes(args):
                targets = []
                for arg in args:
                    if arg.startswith(("-", "(", "!")):
                        break
                    targets.append(arg)
                unknown = False
                # find deletes what matches inside its folders, not the
                # folder itself: the project root may be one.
                whole = False
            else:
                continue
            if unknown:
                return self._delete_reason_unknown(" ".join(args))
            for target in targets:
                expanded = self._expand(target)
                if expanded is _FRESH:
                    continue  # a folder `mktemp` made for this terminal
                if expanded is None:
                    return self._delete_reason_unknown(target)
                path = self._resolve(expanded, self.cwd)
                if path is not None and self._holds_more(path, whole=whole):
                    return self._delete_reason_holds(path)
        return None

    def _learn_variables(self, command: str) -> None:
        """Remember the variables `command` sets (the terminal keeps them):
        a value written out, a fresh `mktemp` folder, or unknown."""
        for match in _ASSIGNMENTS.finditer(command):
            name, value = match.group(1), match.group(2)
            if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) > 1:
                value = value[1:-1]
            if re.match(r"^(\$\(|`)\s*mktemp\b", value):
                self.variables[name] = _FRESH
            elif "$(" in value or "`" in value:
                self.variables[name] = None
            else:
                known = self._expand(value)
                self.variables[name] = None if known is _FRESH else known

    def _expand(self, word: str) -> str | object | None:
        """`word` with its variables replaced: a string, `_FRESH` when it is
        (inside) a fresh `mktemp` folder, None when a variable is unknown.
        A variable the terminal never set is read from the environment it
        inherits (`$TMPDIR`); `$$` (the shell's number) stays a name."""
        word = word.strip("\"'").replace("$$", "0")
        dirname = _DIRNAME.fullmatch(word.split("/", 1)[0]) if word.startswith("$(") else None
        if dirname:
            inner = self._expand(dirname.group(1))
            if inner is _FRESH or inner is None:
                return inner
            rest = word.split("/", 1)[1] if "/" in word else ""
            word = (
                os.path.join(os.path.dirname(str(inner)), rest)
                if rest
                else os.path.dirname(str(inner))
            )
        if "`" in word or "$(" in word:
            return None
        first = _VARIABLE.match(word)
        if first and self.variables.get(first.group(1)) is _FRESH:
            return _FRESH
        unknown = False

        def value(match: re.Match[str]) -> str:
            nonlocal unknown
            name = match.group(1)
            if name == "HOME":
                return self.home
            if name == "PWD":
                return self.cwd
            if name in self.variables:
                known = self.variables[name]
                if isinstance(known, str):
                    return known
            elif name in os.environ:
                return os.environ[name]
            unknown = True
            return ""

        result = _VARIABLE.sub(value, word)
        return None if unknown or "$" in result else result

    def _holds_more(self, path: str, *, whole: bool = True) -> bool:
        """Deleting `path` would delete more than the project's own files.
        `whole=False` (find): the project root itself is fine."""
        if path in ("/", self.home):
            return True
        if _inside(self.root, path) and (whole or path != self.root):
            return True  # the root itself, or a folder above it
        temp = os.path.realpath(tempfile.gettempdir())
        protected = [
            *(os.path.realpath(d) for d in _SYSTEM_DIRS if os.path.exists(d)),
            *(os.path.join(self.home, d) for d in _HOME_TOOL_DIRS),
            temp,
        ]
        return any(_inside(d, path) for d in protected)

    def _delete_reason_unknown(self, target: str) -> str:
        return (
            f"{_DELETE_REASON} whose target is only known when the command runs "
            f"({target}). Write out the path of what you created, inside the project "
            f"root {self.root}."
        )

    def _delete_reason_holds(self, path: str) -> str:
        return (
            f"{_DELETE_REASON} of {path}, which holds more than this project's files "
            "(the project root or a folder above it, the home folder, a system or tool "
            "folder, or the system's temporary folder). Delete only what you created, by "
            "its own path."
        )

    def _resolve(self, value: str, base: str | None) -> str | None:
        """Where `cd value` goes from `base`, or None when a word can't say
        (a variable, `-`, or a relative path from an unknown folder)."""
        value = re.sub(r"^\$\{?HOME\}?", "~", value)
        if value == "-" or "$" in value or "`" in value:
            return None
        expanded = os.path.expanduser(value)
        if os.path.isabs(expanded):
            return os.path.realpath(expanded)
        if base is None:
            return None
        return os.path.realpath(os.path.join(base, expanded))

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
