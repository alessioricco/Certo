"""The scripts in examples/: they run as their comments say. No model call."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parent.parent / "examples" / "certo-mcp-launcher.sh.example"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="a POSIX shell script"
)


def _launcher(tmp_path: Path, workspace: Path) -> Path:
    text = _LAUNCHER.read_text()
    text = text.replace('WORKSPACE="$HOME/certo-mcp-workspace"', f'WORKSPACE="{workspace}"')
    path = tmp_path / "launcher"
    path.write_text(text)
    path.chmod(0o755)
    return path


def _fake_certo(tmp_path: Path) -> Path:
    """Records the arguments and the CERTO_ settings it is started with."""
    fake = tmp_path / "fake-certo"
    record = tmp_path / "record.json"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"open({str(record)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], "
        "'env': {k: v for k, v in os.environ.items() if k.startswith('CERTO_')}}))\n"
    )
    fake.chmod(0o755)
    return fake


def test_the_launcher_starts_certo_mcp_with_its_own_settings(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    env = {**os.environ, "CERTO_BIN": str(_fake_certo(tmp_path)), "CERTO_LLM_MODEL": "other"}

    done = subprocess.run(
        [str(_launcher(tmp_path, workspace)), "--root", "/extra"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert done.stdout == ""  # standard output is the MCP connection
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["argv"] == ["mcp", "--root", str(workspace), "--root", "/extra"]
    assert record["env"]["CERTO_LLM_MODEL"] == "ollama/qwen3.8:27b"  # the launcher's wins
    assert record["env"]["CERTO_PROJECTS_DIR"] == str(workspace)
    assert record["env"]["CERTO_LLM_TIMEOUT_SECONDS"] == "1200"
    assert record["env"]["CERTO_MAX_TASK_SECONDS"] == "3600"
    assert "CERTO_LLM_REASONING_EFFORT" not in record["env"]


def test_the_launcher_stops_with_a_message_when_something_is_missing(tmp_path):
    no_folder = subprocess.run(
        [str(_launcher(tmp_path, tmp_path / "missing"))],
        env={**os.environ, "CERTO_BIN": str(_fake_certo(tmp_path))},
        capture_output=True,
        text=True,
    )
    assert no_folder.returncode == 1
    assert no_folder.stdout == ""
    assert "is not a folder; make it first" in no_folder.stderr

    (tmp_path / "work").mkdir()
    no_certo = subprocess.run(
        [str(_launcher(tmp_path, tmp_path / "work"))],
        env={**os.environ, "CERTO_BIN": "no-such-certo-command"},
        capture_output=True,
        text=True,
    )
    assert no_certo.returncode == 1
    assert "'no-such-certo-command' not found on PATH" in no_certo.stderr
    assert not (tmp_path / "record.json").exists()
