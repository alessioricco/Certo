"""Where Certo finds its model files.

`models_list.yaml` is the catalog (model ids, descriptions, ratings);
`models.yaml` holds the user's personal settings (which models to use,
keys, addresses, overrides). Two more are optional, one per mode:
`task_profiles.yaml` (`--auto-model`) and `escalation.yaml` (`--escalate`,
and `certo bench`). Certo ships all four only as examples, in
`certo/examples/`, and never reads an example: a release can update the
examples without touching anyone's own copies.

Each file is looked up on its own. A path a setting names
(`CERTO_MODELS_LIST_FILE`, `CERTO_MODELS_FILE`, `CERTO_TASK_PROFILES_FILE`,
`CERTO_ESCALATION_FILE`, or a benchmark file's keys) is used alone.
Otherwise the file is read in layers, lowest first: the user settings
folder (next to the user `.env`, `~/.config/certo/`), the current folder,
and the project folder (`--project`); each layer adds to or changes the
one below by name, and `replace: true` at a file's top hides the layers
below it (model_catalog.LayeredPath; DECISIONS.md, 2026-11-14).
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import user_settings_path
from .model_catalog import (
    ESCALATION_FILE,
    LIST_FILE,
    MODELS_FILE,
    PROFILES_FILE,
    LayeredPath,
    ModelCatalogError,
)

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


def user_dir() -> str:
    return os.path.dirname(user_settings_path())


def example_path(name: str) -> str:
    return str(EXAMPLES_DIR / f"{name}.example")


def _search_folders(project_dir: str = "") -> tuple[str, ...]:
    """The folders to look in, highest first: the project, the current
    folder, the user settings folder; each once."""
    seen: list[str] = []
    out: list[str] = []
    for folder in (project_dir, os.getcwd(), user_dir()):
        if not folder:
            continue
        real = os.path.realpath(folder)
        if real not in seen:
            seen.append(real)
            out.append(folder)
    return tuple(out)


def find(name: str, explicit: str = "", project_dir: str = "") -> str | None:
    """The top file for `name` (the one to edit), or None when there is
    none. An explicit path is returned as is, even if missing, so the
    error can name it."""
    if explicit:
        return explicit
    for folder in _search_folders(project_dir):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


# Certo's own model list and task profiles: the lowest layer, read from
# the package (DECISIONS.md, 2026-11-14). The user's files hold only their
# exceptions. models.yaml (which models, which keys) has none.
BUILT_IN = (LIST_FILE, PROFILES_FILE)


def built_in_path(name: str) -> str | None:
    return example_path(name) if name in BUILT_IN else None


def is_built_in(path: str) -> bool:
    return any(os.path.abspath(path) == os.path.abspath(example_path(n)) for n in BUILT_IN)


def with_built_in(name: str, path: str | None) -> str | None:
    """`path` (one user file) read on top of Certo's own file for `name`,
    as a run would; Certo's alone when `path` doesn't exist."""
    base = built_in_path(name)
    if path is None or not os.path.isfile(path):
        return base or path
    if base is None or is_built_in(path) or getattr(path, "layers", None):
        return path
    return LayeredPath([base, path])


def find_layers(name: str, explicit: str = "", project_dir: str = "") -> str | None:
    """The file to read for `name`: an explicit path alone, else every
    layer found, lowest first, starting with Certo's own for the model
    list and the task profiles (a `LayeredPath` when more than one), or
    None."""
    if explicit:
        return explicit
    found = [
        os.path.join(folder, name)
        for folder in reversed(_search_folders(project_dir))
        if os.path.isfile(os.path.join(folder, name))
    ]
    base = built_in_path(name)
    if base is not None and os.path.isfile(base):
        found.insert(0, base)
    if not found:
        return None
    return found[0] if len(found) == 1 else LayeredPath(found)


def layers_of(path: str | None) -> tuple[str, ...]:
    """The files a found path reads, lowest first."""
    if path is None:
        return ()
    return tuple(getattr(path, "layers", None) or (path,))


def missing_message(name: str, setting: str) -> str:
    return (
        f"No {name} found: Certo looked in the current folder and in {user_dir()}. "
        "Run certo init models to set up your models and write it. Or copy the "
        "example Certo ships and edit it:\n"
        f"  cp {example_path(name)} {os.path.join(user_dir(), name)}\n"
        f"(or put it in the project folder, or set {setting})."
    )


def resolve(
    models_file: str = "", models_list_file: str = "", project_dir: str = ""
) -> tuple[str, str]:
    """(models_list.yaml, models.yaml) paths. Raises `ModelCatalogError`
    saying how to create a missing one, or naming an explicit path that
    doesn't exist."""
    paths = []
    for name, explicit, setting in (
        (LIST_FILE, models_list_file, "CERTO_MODELS_LIST_FILE"),
        (MODELS_FILE, models_file, "CERTO_MODELS_FILE"),
    ):
        path = find_layers(name, explicit, project_dir)
        if path is None:
            raise ModelCatalogError(missing_message(name, setting))
        if not os.path.isfile(path):
            raise ModelCatalogError(f"{setting} names {path}, which doesn't exist.")
        paths.append(path)
    return paths[0], paths[1]


def resolve_optional(
    task_profiles_file: str = "", escalation_file: str = "", project_dir: str = ""
) -> tuple[str | None, str | None]:
    """(task_profiles.yaml, escalation.yaml) paths, None for one that isn't
    there: both are optional. A path a setting names must exist."""
    paths: list[str | None] = []
    for name, explicit, setting in (
        (PROFILES_FILE, task_profiles_file, "CERTO_TASK_PROFILES_FILE"),
        (ESCALATION_FILE, escalation_file, "CERTO_ESCALATION_FILE"),
    ):
        path = find_layers(name, explicit, project_dir)
        if path is not None and not os.path.isfile(path):
            raise ModelCatalogError(f"{setting} names {path}, which doesn't exist.")
        paths.append(path)
    return paths[0], paths[1]
