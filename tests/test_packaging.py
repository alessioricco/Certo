"""Builds the real sdist + wheel (`uv build`, exactly as the release workflow
does: the wheel is built from the sdist) and checks what's inside them.

No LLM, no network beyond what `uv build` needs to fetch hatchling. Skipped
when `uv` isn't on PATH.
"""

from __future__ import annotations

import fnmatch
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--quiet", "--out-dir", str(out), str(_REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = out.glob("*.whl")
    (sdist,) = out.glob("*.tar.gz")
    return {"wheel": wheel, "sdist": sdist}


def _wheel_names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        return zf.namelist()


def _sdist_names(sdist: Path) -> list[str]:
    # Strip the leading "certo-X.Y.Z/" so paths read like repo paths.
    with tarfile.open(sdist) as tf:
        return [m.name.split("/", 1)[1] for m in tf.getmembers() if m.isfile()]


# Local state, secrets and caches that must never be published. Matched
# against every path component (directories) or the file name (files).
_FORBIDDEN_DIRS = {
    "projects",
    "artifacts",
    "private",
    "secrets",
    "third_party_skills",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".git",
    # Gitignored Apache-2.0 copies hand-placed in ./skills; not ours to ship.
    "frontend-design",
    "webapp-testing",
    "web-artifacts-builder",
}
_FORBIDDEN_FILES = (
    ".env",
    ".env.local",
    ".envrc",
    "models.yaml",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.pyc",
    ".DS_Store",
    ".pypirc",
    "third_party_skills.lock.json",
)


def _forbidden(paths: list[str]) -> list[str]:
    bad = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if set(parts[:-1]) & _FORBIDDEN_DIRS or any(
            fnmatch.fnmatch(parts[-1], pattern) for pattern in _FORBIDDEN_FILES
        ):
            bad.append(path)
    return bad


def test_wheel_contains_no_secrets_state_or_caches(built):
    assert _forbidden(_wheel_names(built["wheel"])) == []


def test_sdist_contains_no_secrets_state_or_caches(built):
    assert _forbidden(_sdist_names(built["sdist"])) == []


def test_sdist_ships_only_the_allowlisted_paths(built):
    allowed_prefixes = ("src/certo/", "tests/")
    allowed_files = {
        "PKG-INFO",
        ".gitignore",  # hatchling always adds it to an sdist
        "pyproject.toml",
        "README.md",
        "MANUAL.md",
        "LICENSE",
        ".env.example",
        "docker/agent-server.Dockerfile",
    }
    names = _sdist_names(built["sdist"])
    unexpected = [n for n in names if n not in allowed_files and not n.startswith(allowed_prefixes)]
    assert unexpected == []
    assert "src/certo/builtin_skills/lifecycle/repository-discovery.md" in names


def test_wheel_ships_the_builtin_skill_catalog(built):
    names = _wheel_names(built["wheel"])
    shipped = {
        Path(n).relative_to("certo/builtin_skills").as_posix()
        for n in names
        if n.startswith("certo/builtin_skills/")
    }
    repo = {
        p.relative_to(_REPO_ROOT / "src/certo/builtin_skills").as_posix()
        for p in (_REPO_ROOT / "src/certo/builtin_skills").rglob("*.md")
    }
    assert repo, "no built-in skills found in the source tree"
    assert repo <= shipped
    assert any(n.startswith("lifecycle/") for n in shipped)


def test_wheel_ships_certos_model_list_and_the_examples(built):
    # Certo's own list and profiles are read from the package; the other
    # model files ship as examples, so an installed Certo can tell users
    # what to copy.
    names = set(_wheel_names(built["wheel"]))
    assert "certo/data/models_list.yaml" in names
    assert "certo/data/task_profiles.yaml" in names
    assert "certo/data/model_data.json" in names  # the third-party scores (model_data.py)
    # Put back by their exact paths: the excludes and .gitignore keep out
    # every other copy (a user's).
    sdist = set(_sdist_names(built["sdist"]))
    assert {
        "src/certo/data/models_list.yaml",
        "src/certo/data/task_profiles.yaml",
        "src/certo/data/model_data.json",
    } <= sdist
    for name in ("models_list.yaml", "task_profiles.yaml"):
        assert [n for n in names if n.endswith(name)] == [f"certo/data/{name}"]
    assert "certo/examples/models.yaml.example" in names
    assert "certo/examples/escalation.yaml.example" in names
    assert "certo/examples/bench.yaml.example" in names


def test_wheel_ships_the_benchmark_task_set(built):
    # `certo bench` runs from an installed wheel: every task file, hidden
    # tests and reference solutions included, must be in it.
    names = set(_wheel_names(built["wheel"]))
    root = _REPO_ROOT / "src/certo/benchmark_tasks"
    repo = {
        "certo/benchmark_tasks/" + p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert "certo/benchmark_tasks/VERSION" in repo
    assert any("/hidden_tests/" in n for n in repo)
    assert repo <= names


def test_wheel_ships_the_certo_init_starter_files(built):
    # `certo init` works offline: everything it writes comes from the package.
    names = set(_wheel_names(built["wheel"]))
    repo = {
        "certo/starter/" + p.relative_to(_REPO_ROOT / "src/certo/starter").as_posix()
        for p in (_REPO_ROOT / "src/certo/starter").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert {
        "certo/starter/providers.toml",
        "certo/starter/README.md",
        "certo/starter/gitignore",
        "certo/starter/tasks/wordle.md",
        "certo/starter/tasks/space-rocks.md",
        "certo/starter/tasks/hanoi.md",
        "certo/starter/tasks/mazeman.md",
        "certo/starter/tasks/invaders.md",
    } <= repo
    assert repo <= names


def test_wheel_installs_exactly_the_certo_console_scripts(built):
    with zipfile.ZipFile(built["wheel"]) as zf:
        (ep_name,) = [n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")]
        entry_points = zf.read(ep_name).decode()
    section = entry_points.split("[console_scripts]", 1)[1].split("[", 1)[0]
    scripts = {line.split("=")[0].strip() for line in section.splitlines() if "=" in line}
    assert scripts == {"certo", "certo-server", "certo-admin"}
