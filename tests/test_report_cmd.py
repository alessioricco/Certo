"""report_cmd.py: `certo report`, the last run's problems in one file, with
keys hidden. No LLM: the `.certo/` folder is built by hand."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from certo import report_cmd
from certo.project_state import RunRecord, ensure_state_dir
from certo.report_cmd import HIDDEN, hide_secrets, report_main, secrets_in_settings

_FAKE_KEY = "sk-ant-test0000000000000000000000"  # not a real key


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No settings or model files from this computer: an empty user folder,
    and a current folder with nothing in it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CERTO_MODELS_FILE", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)


def _project(tmp_path, *, errors=(), page="# Run report · failed\n\n## Task\n\n> do it\n"):
    project = tmp_path / "demo"
    state = ensure_state_dir(str(project))
    record = RunRecord(
        task="Build a ledger\nwith tests",
        conversation_id="abc123",
        model="anthropic/claude-haiku-5-5",
        execution="local",
        started_at="2026-11-16T10:00:00+00:00",
        updated_at="2026-11-16T10:20:00+00:00",
        status="finished",
        verdict="failed",
        retries_used=2,
        max_task_seconds=1800,
        max_iterations=50,
    )
    with open(os.path.join(state, "run.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(record), f)
    events = os.path.join(state, "conversations", "abc123", "events")
    os.makedirs(events)
    for i, event in enumerate([{"kind": "MessageEvent"}, *errors]):
        with open(os.path.join(events, f"event-{i:05d}.json"), "w", encoding="utf-8") as f:
            json.dump(event, f)
    if page is not None:
        os.makedirs(os.path.join(state, "reports"))
        with open(
            os.path.join(state, "reports", "2026-11-16T10-00-00Z.md"), "w", encoding="utf-8"
        ) as f:
            f.write(page)
    return project


def test_no_recorded_run_is_an_error(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert report_main([str(tmp_path / "empty")]) == 1
    assert "No run recorded" in capsys.readouterr().err


def test_the_report_has_the_run_the_sdk_errors_the_page_and_the_note(tmp_path, capsys):
    errors = [
        {
            "kind": "ConversationErrorEvent",
            "timestamp": "2026-11-16T10:05:00.1",
            "code": "LLMTimeoutError",
            "detail": "litellm.Timeout: Connection timed out after 300 seconds.",
        },
        {"kind": "AgentErrorEvent", "tool_name": "terminal", "error": "bad arguments"},
        {"kind": "UserRejectObservation", "tool_name": "file_editor", "rejection_reason": "x"},
    ]
    page = "# Run report · failed\n\n## Checks\n\n```text\n# a comment in output\n```\n"
    project = _project(tmp_path, errors=errors, page=page)

    assert report_main([str(project), "--note", "It stopped at milestone 2."]) == 0
    path = project / ".certo" / "certo-report.md"
    assert f"Report: {path}" in capsys.readouterr().out
    text = path.read_text(encoding="utf-8")
    assert "> It stopped at milestone 2." in text
    assert "- Task: Build a ledger\n" in text
    assert "- How it ended: finished, verdict `failed`" in text
    assert "- Time budget: 30m 00s" in text and "- Step limit: 50" in text
    assert "LLMTimeoutError: litellm.Timeout: Connection timed out after 300 seconds." in text
    assert "tool `terminal`: bad arguments" in text
    assert "action rejected, tool `file_editor`: x" in text
    # The page sits one level down; a line in a code block is left alone.
    assert "## Run report · failed\n" in text and "### Checks\n" in text
    assert "\n# a comment in output\n" in text


def test_a_run_with_no_error_says_none_and_output_goes_where_asked(tmp_path):
    project = _project(tmp_path)
    out = tmp_path / "shared" / "report.md"
    assert report_main([str(project), "--output", str(out)]) == 0
    assert "## Errors the SDK recorded\n\nNone.\n" in out.read_text(encoding="utf-8")


def test_keys_from_settings_models_yaml_and_key_shapes_are_hidden(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MY_PROVIDER_API_KEY", "abcdefghijkl-env-secret")
    project = _project(
        tmp_path,
        errors=[
            {
                "kind": "ConversationErrorEvent",
                "code": "AuthError",
                "detail": f"bad key {_FAKE_KEY} and abcdefghijkl-env-secret and dotenv-secret-123",
            }
        ],
        page="# Run report\n\nmodels key: yaml-secret-value-1 · budget 12000000\n",
    )
    (project / ".env").write_text("OTHER_TOKEN=dotenv-secret-123\n")
    (project / "models.yaml").write_text(
        "models:\n  - name: a\n    api_key: yaml-secret-value-1\n"
        "  - name: b\n    api_key: ${MY_PROVIDER_API_KEY}\n"
    )

    assert report_main([str(project)]) == 0
    text = (project / ".certo" / "certo-report.md").read_text(encoding="utf-8")
    for secret in (
        _FAKE_KEY,
        "abcdefghijkl-env-secret",
        "dotenv-secret-123",
        "yaml-secret-value-1",
    ):
        assert secret not in text
    assert text.count(HIDDEN) >= 4
    assert "budget 12000000" in text
    out = capsys.readouterr().out
    assert "were replaced with [hidden]" in out
    assert "secret" not in out


def test_only_secret_looking_settings_are_hidden():
    found = secrets_in_settings(
        {
            "CERTO_TRUSTED_SKILLS_TOKENS": "4000",
            "CERTO_MAX_TOKENS": "120000000000",
            "GITHUB_TOKEN": "a-long-token-value",
            "CERTO_LLM_MODEL": "anthropic/claude-haiku-5-5",
        }
    )
    assert found == {"a-long-token-value"}


def test_hide_secrets_counts_what_it_replaced():
    text, count = hide_secrets("Authorization: Bearer abcdefghijklmnop1234 x", set())
    assert (text, count) == (f"Authorization: Bearer {HIDDEN} x", 1)
    assert hide_secrets("nothing here", {"zzzzzzzzzzzzzz"}) == ("nothing here", 0)


def test_the_newest_report_page_is_used(tmp_path):
    project = _project(tmp_path, page="# Run report · old\n")
    with open(
        project / ".certo" / "reports" / "2026-11-17T08-00-00Z.md", "w", encoding="utf-8"
    ) as f:
        f.write("# Run report · new\n")
    text = report_cmd.render(str(project), now=datetime(2026, 11, 17, tzinfo=UTC))
    assert "Run report · new" in text and "Run report · old" not in text
