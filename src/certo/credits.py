"""A short credit for Certo in the projects it creates.

In a project Certo created from scratch (worktree.was_created_by_certo),
before the checks run, Certo itself adds (once, never twice):

- a closing line to README.md: "Generated with [Certo](URL).";
- `<meta name="generator" content="Certo (URL)">` in the `<head>` of each
  index.html near the top of the project (not in build output or
  dependencies).

Done by Certo, not asked of the agent: it is always the same, costs no
model tokens and doesn't change what the agent does. An existing project
Certo is pointed at is never touched. CERTO_CREDITS=no turns it off.
"""

from __future__ import annotations

import os
import re

CERTO_URL = "https://github.com/alessioricco/Certo"
README_LINE = f"Generated with [Certo]({CERTO_URL})."
META_TAG = f'<meta name="generator" content="Certo ({CERTO_URL})">'

# Folders where an index.html is build output or a dependency, never the
# project's own page.
_SKIP_DIRS = {
    "node_modules",
    "dist",
    "build",
    "coverage",
    "playwright-report",
    "test-results",
    ".git",
    ".certo",
    ".venv",
    "venv",
    "__pycache__",
}
_MAX_DEPTH = 2  # index.html at the top, or one or two folders down (public/, src/)
_HEAD = re.compile(r"<head[^>]*>", re.IGNORECASE)


def _readme(workspace: str) -> str | None:
    for name in ("README.md", "readme.md", "Readme.md"):
        path = os.path.join(workspace, name)
        if os.path.isfile(path):
            return path
    return None


def add_readme_credit(workspace: str) -> bool:
    """Add the credit line to README.md. False when there is none, or it
    already names Certo's URL."""
    path = _readme(workspace)
    if path is None:
        return False
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if CERTO_URL.lower() in text.lower():
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(("" if text.endswith("\n") else "\n") + "\n---\n\n" + README_LINE + "\n")
    return True


def index_pages(workspace: str) -> list[str]:
    """The project's own index.html files, near the top."""
    found = []
    root_depth = workspace.rstrip(os.sep).count(os.sep)
    for folder, dirs, files in os.walk(workspace):
        depth = folder.rstrip(os.sep).count(os.sep) - root_depth
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        if depth >= _MAX_DEPTH:
            dirs[:] = []
        if "index.html" in files:
            found.append(os.path.join(folder, "index.html"))
    return sorted(found)


def add_meta_credit(path: str) -> bool:
    """Add the generator meta tag after `<head>`. False when the page has
    no `<head>`, or already names Certo's URL."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if CERTO_URL.lower() in text.lower():
        return False
    head = _HEAD.search(text)
    if head is None:
        return False
    line_start = text.rfind("\n", 0, head.start()) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group(0) + "  "
    insert = f"\n{indent}{META_TAG}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[: head.end()] + insert + text[head.end() :])
    return True


def add_credits(workspace: str) -> list[str]:
    """Add every credit that is missing. Returns the files changed, relative
    to `workspace`. Never raises."""
    changed = []
    try:
        if add_readme_credit(workspace):
            changed.append(os.path.basename(_readme(workspace) or "README.md"))
        for page in index_pages(workspace):
            if add_meta_credit(page):
                changed.append(os.path.relpath(page, workspace))
    except OSError:
        pass
    return changed
