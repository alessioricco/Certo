"""The project root: choosing it before the agent starts.

In a Certo workspace (a folder with a `projects/` folder, as `certo init`
makes) a task run without `--project` would otherwise make the whole
workspace the agent's folder: the agent then picks a subfolder itself,
reads the other projects, and Certo's checks find several projects and
can't tell which one to verify. Instead Certo names the project after the
task and runs it in `projects/<name>`, as if `--project <name>` was given.

The name is deterministic (no model call): a task file's or URL's name,
else the task's Markdown title, else its first words.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from .config import resolve_project_dir

# Words that say nothing about the project, left out of a name made from
# the task's first words.
_FILLER = frozenset(
    "a an the this that these those in into on of for to with and or as at by from "
    "build create make write add implement develop design generate set up please "
    "app application project program simple small new my our your which is are be "
    "using use it its".split()
)
_MAX_WORDS = 4
_MAX_LENGTH = 40
FALLBACK_NAME = "project"


def slugify(text: str) -> str:
    """Lowercase letters, digits and single hyphens, at most `_MAX_LENGTH`
    characters, cut at a hyphen. Empty when nothing is left."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > _MAX_LENGTH:
        slug = (
            slug[:_MAX_LENGTH].rsplit("-", 1)[0]
            if "-" in slug[:_MAX_LENGTH]
            else slug[:_MAX_LENGTH]
        )
    return slug.strip("-")


def _title(text: str) -> str | None:
    """The task's Markdown title, when its first non-empty line is one."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"#+\s+(.*)", line)
        return match.group(1) if match else None
    return None


def _first_words(text: str) -> str:
    # A hyphenated word ("to-do", "command-line") stays one word.
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
    kept = [w for w in words if w not in _FILLER]
    return "-".join(kept[:_MAX_WORDS])


def project_name_for_task(source: str, text: str) -> str:
    """A project name for a task. `source` is the task argument as given (a
    file path, a URL or the text itself); `text` is the task text."""
    if source != text:
        path = urlparse(source).path if re.match(r"https?://", source) else source
        stem = os.path.splitext(os.path.basename(path.rstrip("/")))[0]
        name = slugify(stem)
        if name and name not in {"task", "tasks", "readme", "index", "spec"}:
            return name
    title = _title(text)
    if title:
        name = slugify(_first_words(title)) or slugify(title)
        if name:
            return name
    return slugify(_first_words(text)) or FALLBACK_NAME


def is_certo_workspace(folder: str, projects_dir: str) -> bool:
    """A folder where tasks get their own project folder: it has the
    projects folder, and isn't itself a project (no manifest or source
    file at its top level)."""
    from .verification import detect_project

    if not os.path.isdir(projects_dir):
        return False
    detection = detect_project(folder)
    if detection.language in ("unknown", "ambiguous"):
        return True
    return os.path.realpath(detection.root) != os.path.realpath(folder)


def unused_project_name(projects_dir: str, name: str) -> str:
    """`name`, or `name-2`, `name-3`... when that folder already exists."""
    candidate, number = name, 1
    while os.path.exists(resolve_project_dir(projects_dir, candidate)):
        number += 1
        candidate = f"{name}-{number}"
    return candidate
