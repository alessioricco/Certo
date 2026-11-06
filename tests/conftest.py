"""Shared test helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import tempfile

import pytest

# Certo reads a user settings file from $XDG_CONFIG_HOME/certo/.env. Point
# it at an empty temporary folder before any test module is imported (some
# call load_config() at collection time), so no test reads or writes the
# real ~/.config. Tests that need the file set their own folder.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="certo-tests-xdg-")


@pytest.fixture(autouse=True)
def user_plugins_dir(tmp_path_factory, monkeypatch):
    """The SDK's user plugin folders (`~/.agents/plugins`, `~/.openhands/plugins`,
    the installed store), fixed when it is imported, pointed at an empty
    temporary folder: no test sees the developer's own OpenHands plugins, and
    a test can add one under the returned folder (plugins.py)."""
    from openhands.sdk.plugin import discovery, installed

    root = tmp_path_factory.mktemp("user-plugins")
    monkeypatch.setattr(discovery, "USER_PLUGINS_DIRS", [root / "agents", root / "openhands"])
    monkeypatch.setattr(installed, "DEFAULT_INSTALLED_PLUGINS_DIR", root / "installed")
    return root / "agents"


@pytest.fixture(autouse=True)
def no_ollama_server(monkeypatch):
    """No test asks a real Ollama server for its context window, version,
    model digest or capabilities (context_window.py); a test that needs it
    patches its own."""
    from certo import context_window

    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: None)
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: None)
    monkeypatch.setattr(context_window, "ollama_model_digest", lambda *a, **k: None)
    monkeypatch.setattr(context_window, "ollama_capabilities", lambda *a, **k: None)
    monkeypatch.setattr("certo.llm.ollama_context_tokens", lambda *a, **k: None)


def make_project_venv(project_dir) -> str:
    """Give `project_dir` a `.venv` that can already import pytest and ruff,
    without the network: a pip-less venv from the test interpreter, with a
    `.pth` pointing at the test environment's site-packages.

    Verification then finds and reuses this environment instead of creating
    one and installing pytest from the index. Test-only: the product never
    links a project environment to its own.
    """
    venv = os.path.join(str(project_dir), ".venv")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", venv], check=True)
    site = sysconfig.get_path("purelib", vars={"base": venv, "platbase": venv})
    with open(os.path.join(site, "certo_tests.pth"), "w", encoding="utf-8") as f:
        f.write(sysconfig.get_path("purelib") + "\n")
    return venv


@pytest.fixture
def project_venv():
    return make_project_venv


@pytest.fixture
def make_symlink():
    """Skip only when Windows explicitly denies symlink creation privileges."""

    def create(link, target, *, target_is_directory=False):
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows symlink creation requires Developer Mode or symlink privilege")
            raise

    return create


@pytest.fixture(params=["symlink", *(["junction"] if os.name == "nt" else [])])
def directory_link(request, make_symlink):
    """Exercise directory containment with symlinks and real Windows junctions."""

    def create(link, target):
        if request.param == "symlink":
            make_symlink(link, target, target_is_directory=True)
        else:
            subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
                text=True,
            )

    return create


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _never_read_the_real_model_files(monkeypatch):
    """The repository root may hold the developer's own models.yaml (with
    keys) and models_list.yaml: never look there. Tests that need model
    files write their own, or change into a temporary folder."""
    from certo import model_files

    def folders():
        cwd = os.getcwd()
        others = (model_files.user_dir(),)
        return others if os.path.realpath(cwd) == os.path.realpath(_REPO_ROOT) else (cwd, *others)

    monkeypatch.setattr(model_files, "_search_folders", folders)


@pytest.fixture(autouse=True)
def _restore_environ():
    """Undo whatever a test leaves in os.environ. load_config() copies .env
    and user-file values into it, which monkeypatch doesn't track."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def model_files():
    from model_file_helpers import write_model_files

    return write_model_files
