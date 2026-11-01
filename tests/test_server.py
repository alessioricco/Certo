"""Server tests. No LLM/network: run_task/stream_task are monkeypatched, same
pattern as test_cli.py. Skips cleanly when the optional "server" extra
(fastapi/uvicorn/httpx) isn't installed.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from certo import server
from certo.config import Config, ConfigError
from certo.runner import CompletionContract, TaskOutcome


def _fake_outcome(verification_state: str = "verified", limitations=()) -> TaskOutcome:
    """The `TaskOutcome` `stream_task` now returns — fakes standing in for
    it in these tests need to return one instead of `None` so `server.py`'s
    `outcome.verification_state` access doesn't blow up."""
    contract = CompletionContract(
        goal="do something",
        acceptance_criteria=[],
        verification_checks=[],
        limitations=list(limitations),
    )
    return TaskOutcome(verification_state=verification_state, completion_contract=contract)


def _wait_for_status(client, task_id, *, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/tasks/{task_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s")


def _cfg(**overrides) -> Config:
    base = dict(
        model="openai/gpt-4o",
        api_key="key",
        base_url=None,
        workspace=".",
        max_iterations=10,
        confirm_mode="never",
        execution="local",
    )
    base.update(overrides)
    return Config(**base)


@pytest.fixture(autouse=True)
def _isolated_server(monkeypatch, tmp_path):
    """Every test runs in its own empty folder with a model configured, so
    no test reads the current folder's `.env` or leaves project folders in
    it. Tests that need another config patch `load_config` again."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, role: str, text: str) -> None:
        self.role = role
        self.content = [_FakeContent(text)]

    def model_dump(self, mode: str = "python") -> dict:
        return {"role": self.role, "content": [{"text": c.text} for c in self.content]}


def test_health():
    client = TestClient(server.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_task_returns_immediately_with_pending_status(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["task"] = task
        calls["cfg"] = cfg
        on_message(_FakeMessage("assistant", "all done"))
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] in ("pending", "running", "completed")
    task_id = body["task_id"]

    final = _wait_for_status(client, task_id)
    assert final["status"] == "completed"
    assert final["final_message"] == "all done"
    assert final["verification_state"] == "verified"
    assert final["completion_contract"] is not None
    assert calls["task"] == "do something"
    assert calls["cfg"].execution == "local"


def test_create_task_passes_the_record_id_and_project_as_run_id_and_project(monkeypatch, tmp_path):
    # So a task's artifacts folder (CERTO_ARTIFACTS_DIR) is named after
    # the exact same id GET /tasks/{id} returns.
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **kwargs):
        calls["run_id"] = kwargs.get("run_id")
        calls["project"] = kwargs.get("project")
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something", "project": "my-api"}).json()[
        "task_id"
    ]
    _wait_for_status(client, task_id)

    assert calls["run_id"] == task_id
    assert calls["project"] == "my-api"


def test_create_task_with_project_creates_subfolder(monkeypatch, tmp_path):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something", "project": "myapp"})
    task_id = response.json()["task_id"]
    _wait_for_status(client, task_id)

    expected = str(tmp_path / "myapp")
    assert calls["cfg"].workspace == expected
    assert (tmp_path / "myapp").is_dir()


def test_create_task_rejects_a_project_path_escape_attempt(monkeypatch, tmp_path):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("stream_task should not be called")

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "stream_task", _fail_if_called)

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something", "project": "/etc/cron.d"})

    assert response.status_code == 400
    assert "must be relative, not absolute" in response.json()["detail"]


def test_create_task_agents_md_without_project_returns_400(monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: _cfg())

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something", "agents_md": "content"})

    assert response.status_code == 400
    assert "agents_md requires project" in response.json()["detail"]


def test_create_task_agents_md_with_project_writes_file(monkeypatch, tmp_path):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/tasks",
        json={
            "task": "do something",
            "project": "myapp",
            "agents_md": "This project uses FastAPI.",
        },
    )
    _wait_for_status(client, response.json()["task_id"])

    assert (tmp_path / "myapp" / "AGENTS.md").read_text() == "This project uses FastAPI."


def test_create_task_with_model_override_swaps_llm_without_env(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/tasks",
        json={
            "task": "do something",
            "model": "openai/gpt-4o",
            "api_key": "sk-other",
            "base_url": "http://localhost:11434",
        },
    )
    _wait_for_status(client, response.json()["task_id"])

    assert calls["cfg"].model == "openai/gpt-4o"
    assert calls["cfg"].api_key == "sk-other"
    assert calls["cfg"].base_url == "http://localhost:11434"


def test_create_task_with_reasoning_effort_override(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/tasks",
        json={"task": "do something", "reasoning_effort": "low"},
    )
    _wait_for_status(client, response.json()["task_id"])

    assert calls["cfg"].reasoning_effort == "low"
    assert calls["cfg"].model == "anthropic/claude-x"


def test_create_task_reasoning_effort_off_is_normalized(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something", "reasoning_effort": "off"})
    _wait_for_status(client, response.json()["task_id"])

    assert calls["cfg"].reasoning_effort == "none"


def test_create_task_without_override_keeps_configured_model(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    response = client.post("/tasks", json={"task": "do something"})
    _wait_for_status(client, response.json()["task_id"])

    assert calls["cfg"].model == "anthropic/claude-x"


def test_create_app_raises_immediately_on_a_config_error(monkeypatch):
    # load_config() is now called once at create_app() time (to build the
    # task store), not deferred to the first request — a config error
    # (missing CERTO_LLM_MODEL, etc.) fails fast at server startup instead of
    # silently starting a server that only reveals the problem later.
    def _raise() -> Config:
        raise ConfigError("CERTO_LLM_MODEL is required")

    monkeypatch.setattr(server, "load_config", _raise)

    with pytest.raises(ConfigError, match="CERTO_LLM_MODEL is required"):
        server.create_app()


def test_get_task_reports_failure(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]

    final = _wait_for_status(client, task_id)
    assert final["status"] == "failed"
    assert "boom" in final["error"]
    assert final["final_message"] is None


def test_get_task_status_completed_does_not_imply_verification_passed(monkeypatch):
    # `status` only ever meant "the run didn't raise" — a task whose
    # verification retries were exhausted still ends with status
    # "completed" (no exception), so a poller must check
    # `verification_state`, not just `status`, to know whether it actually
    # succeeded. See MANUAL.md "Test verification".
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(verification_state="retry_exhausted", limitations=["pytest: 2 failed"])

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "completed"
    assert final["verification_state"] == "retry_exhausted"
    assert final["completion_contract"]["limitations"] == ["pytest: 2 failed"]


# --- require_verification: opt-in strict treatment of "inconclusive" ------


def test_create_task_inconclusive_defaults_to_completed_status(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(
            verification_state="inconclusive",
            limitations=["No automated check could be run for this project."],
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "completed"
    assert final["verification_state"] == "inconclusive"


def test_create_task_require_verification_turns_unknown_project_into_failure(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(
            verification_state="inconclusive",
            limitations=["No automated check could be run for this project."],
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "failed"
    assert final["verification_state"] == "inconclusive"
    assert "No automated check could be run" in final["error"]


def test_create_task_require_verification_turns_unchanged_into_failure(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(
            verification_state="unchanged", limitations=["The agent changed no file."]
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "failed"
    assert final["error"].startswith("Verification was unchanged and require_verification=true")


def test_create_task_require_verification_turns_a_missing_tool_into_failure(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(
            verification_state="inconclusive",
            limitations=["npm is required to verify this project but was not found on PATH."],
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "failed"


def test_create_task_require_verification_turns_no_tests_collected_into_failure(monkeypatch):
    # The quiet "pytest collected zero tests" case is still just
    # "inconclusive" from the caller's point of view — require_verification
    # doesn't special-case it.
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(verification_state="inconclusive", limitations=[])

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "failed"


def test_create_task_require_verification_does_not_affect_a_real_verified_pass(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(verification_state="verified")

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "completed"


def test_create_task_require_verification_does_not_change_other_verification_states(monkeypatch):
    # require_verification only special-cases "inconclusive" — every other
    # verification_state keeps its existing status semantics unchanged
    # ("completed" means the run didn't raise, never "verification passed";
    # see test_get_task_status_completed_does_not_imply_verification_passed).
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(verification_state="retry_exhausted", limitations=["pytest: 2 failed"])

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "require_verification": True}
    ).json()["task_id"]

    final = _wait_for_status(client, task_id)

    assert final["status"] == "completed"
    assert final["error"] is None  # unchanged: no require_verification message stapled on
    assert final["verification_state"] == "retry_exhausted"


def test_stream_task_require_verification_sends_error_event_for_inconclusive(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        on_message(_FakeMessage("assistant", "done"))
        return _fake_outcome(
            verification_state="inconclusive",
            limitations=["No automated check could be run for this project."],
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something", "require_verification": True})
        ws.receive_json()  # the "message" event
        result = ws.receive_json()

    assert result["type"] == "error"
    assert "No automated check could be run" in result["detail"]


# --- acceptance_checks: opt-in machine-checkable acceptance criteria -------


def test_create_task_rejects_invalid_acceptance_checks(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("stream_task should not be called")

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fail_if_called)

    client = TestClient(server.create_app())
    response = client.post(
        "/tasks",
        json={
            "task": "do something",
            "acceptance_checks": [{"kind": "run_command", "path": "x"}],
        },
    )

    assert response.status_code == 400
    assert "Unknown acceptance check kind" in response.json()["detail"]


def test_create_task_passes_parsed_acceptance_checks_to_stream_task(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["acceptance_checks"] = acceptance_checks
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks",
        json={
            "task": "do something",
            "acceptance_checks": [{"kind": "file_exists", "path": "OUTPUT.txt"}],
        },
    ).json()["task_id"]
    _wait_for_status(client, task_id)

    assert calls["acceptance_checks"][0].path == "OUTPUT.txt"


def test_create_task_without_acceptance_checks_passes_none(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["acceptance_checks"] = acceptance_checks
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    _wait_for_status(client, task_id)

    assert calls["acceptance_checks"] is None


def test_get_task_exposes_acceptance_results(monkeypatch):
    from certo.acceptance import AcceptanceCheck, AcceptanceCheckResult

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        contract = CompletionContract(
            goal="do something", acceptance_criteria=[], verification_checks=[], limitations=[]
        )
        return TaskOutcome(
            verification_state="verified",
            completion_contract=contract,
            acceptance_results=(
                AcceptanceCheckResult(
                    check=AcceptanceCheck(kind="file_exists", path="OUTPUT.txt"),
                    passed=True,
                    detail="OUTPUT.txt exists",
                ),
            ),
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    final = _wait_for_status(client, task_id)

    assert final["acceptance_results"] == [
        {
            "check": {
                "kind": "file_exists",
                "path": "OUTPUT.txt",
                "contains": None,
                "required": True,
                "description": None,
            },
            "passed": True,
            "detail": "OUTPUT.txt exists",
        }
    ]


def test_get_task_acceptance_results_is_none_when_not_supplied(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    final = _wait_for_status(client, task_id)

    assert final["acceptance_results"] is None


def test_stream_task_result_event_includes_acceptance_results(monkeypatch):
    from certo.acceptance import AcceptanceCheck, AcceptanceCheckResult

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        contract = CompletionContract(
            goal="do something", acceptance_criteria=[], verification_checks=[], limitations=[]
        )
        return TaskOutcome(
            verification_state="acceptance_failed",
            completion_contract=contract,
            acceptance_results=(
                AcceptanceCheckResult(
                    check=AcceptanceCheck(kind="file_exists", path="OUTPUT.txt"),
                    passed=False,
                    detail="OUTPUT.txt does not exist",
                ),
            ),
        )

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something"})
        result = ws.receive_json()

    assert result["type"] == "result"
    assert result["verification_state"] == "acceptance_failed"
    assert result["acceptance_results"][0]["passed"] is False


def test_get_task_unknown_id_returns_404():
    client = TestClient(server.create_app())

    response = client.get("/tasks/does-not-exist")

    assert response.status_code == 404


def test_create_task_with_project_field_is_retrievable(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post(
        "/tasks", json={"task": "do something", "project": "acme-website"}
    ).json()["task_id"]

    _wait_for_status(client, task_id)
    # `project` isn't echoed on GET /tasks/{id} today (no caller needs it
    # back), but it must have been stored — proven indirectly via
    # delete-by-project actually finding and removing this task below.
    delete_response = client.delete("/tasks", params={"project": "acme-website"})
    assert delete_response.status_code == 200
    assert delete_response.json() == {"project": "acme-website", "deleted": 1}
    assert client.get(f"/tasks/{task_id}").status_code == 404


def test_delete_task_removes_it(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    _wait_for_status(client, task_id)

    response = client.delete(f"/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json() == {"task_id": task_id, "deleted": True}
    assert client.get(f"/tasks/{task_id}").status_code == 404


def test_delete_task_unknown_id_returns_404():
    client = TestClient(server.create_app())

    response = client.delete("/tasks/does-not-exist")

    assert response.status_code == 404


def test_delete_tasks_by_project_only_removes_matching_project(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    kept_id = client.post("/tasks", json={"task": "t1", "project": "keep-me"}).json()["task_id"]
    doomed_id = client.post("/tasks", json={"task": "t2", "project": "delete-me"}).json()["task_id"]
    _wait_for_status(client, kept_id)
    _wait_for_status(client, doomed_id)

    response = client.delete("/tasks", params={"project": "delete-me"})

    assert response.status_code == 200
    assert response.json() == {"project": "delete-me", "deleted": 1}
    assert client.get(f"/tasks/{doomed_id}").status_code == 404
    assert client.get(f"/tasks/{kept_id}").status_code == 200


def test_delete_tasks_by_project_unknown_project_returns_zero():
    client = TestClient(server.create_app())

    response = client.delete("/tasks", params={"project": "never-existed"})

    assert response.status_code == 200
    assert response.json() == {"project": "never-existed", "deleted": 0}


def test_get_task_reflects_partial_progress(monkeypatch):
    started = threading.Event()
    finish = threading.Event()

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        on_message(_FakeMessage("assistant", "step one"))
        started.set()
        finish.wait(timeout=2)
        on_message(_FakeMessage("assistant", "step two"))
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]

    assert started.wait(timeout=2), "background task never reached the first message"
    mid = client.get(f"/tasks/{task_id}").json()
    assert mid["status"] == "running"
    assert len(mid["messages"]) == 1

    finish.set()
    final = _wait_for_status(client, task_id)
    assert len(final["messages"]) == 2


def test_stream_task_sends_messages_then_closes(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        on_message(_FakeMessage("assistant", "step one"))
        on_message(_FakeMessage("assistant", "done"))
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something"})
        first = ws.receive_json()
        second = ws.receive_json()

    assert first["type"] == "message"
    assert first["content"][0]["text"] == "step one"
    assert second["content"][0]["text"] == "done"


def test_stream_task_sends_a_final_result_event_with_verification_state(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        on_message(_FakeMessage("assistant", "done"))
        return _fake_outcome(verification_state="retry_exhausted", limitations=["pytest: 2 failed"])

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something"})
        ws.receive_json()  # the "message" event
        result = ws.receive_json()

    assert result["type"] == "result"
    assert result["verification_state"] == "retry_exhausted"
    assert result["completion_contract"]["limitations"] == ["pytest: 2 failed"]


def test_stream_task_with_model_override_swaps_llm(monkeypatch):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        calls["cfg"] = cfg
        on_message(_FakeMessage("assistant", "done"))
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something", "model": "openai/gpt-4o"})
        ws.receive_json()

    assert calls["cfg"].model == "openai/gpt-4o"


def test_stream_task_per_request_config_error_sends_error_and_closes(monkeypatch):
    # load_config() itself succeeds at create_app() startup (see
    # test_create_app_raises_immediately_on_a_config_error for that case)
    # — this covers a per-request config problem inside _resolve_cfg
    # still surfacing cleanly as a WS error rather than an unhandled
    # exception, the same way POST /tasks already does.
    monkeypatch.setattr(server, "load_config", lambda: _cfg())

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something", "agents_md": "content"})
        message = ws.receive_json()

    assert message["type"] == "error"
    assert "agents_md requires project" in message["detail"]


# --- OpenAI-compatible /v1/... ---


def test_narrative_texts_skips_system_and_user_only():
    # Regression test: an earlier version filtered to role == "assistant",
    # which silently dropped everything — live testing showed the SDK puts
    # human-readable text (including the final "finish" message) on `tool`-
    # role messages, not `assistant`-role ones (those carry empty content +
    # tool_calls instead).
    messages = [
        _FakeMessage("system", "system prompt"),
        _FakeMessage("user", "hi"),
        _FakeMessage("assistant", "hello"),
        _FakeMessage("tool", "some tool output"),
        _FakeMessage("assistant", "done"),
    ]

    assert server._narrative_texts(messages) == ["hello", "some tool output", "done"]


def test_task_from_chat_messages_concatenates_system_and_last_user():
    class _Msg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    messages = [
        _Msg("system", "You are a helpful assistant."),
        _Msg("user", "first question"),
        _Msg("assistant", "first answer"),
        _Msg("user", "second question"),
    ]

    task = server._task_from_chat_messages(messages)

    assert task == "You are a helpful assistant.\n\nsecond question"


def test_task_from_chat_messages_requires_a_user_message():
    class _Msg:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    with pytest.raises(ValueError, match="at least one 'user' message"):
        server._task_from_chat_messages([_Msg("system", "context only")])


def test_list_models_reflects_configured_model(monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))

    client = TestClient(server.create_app())
    response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["id"] == "anthropic/claude-x"


def test_chat_completions_returns_openai_shaped_response(monkeypatch):
    calls = {}

    def _fake_run_task(task, cfg=None, **_kwargs):
        calls["task"] = task
        calls["cfg"] = cfg
        # Matches reality (confirmed live): the agent's human-readable
        # "finish" text arrives as a tool-role message, not assistant-role.
        return [_FakeMessage("tool", "The answer is 4.")]

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "What is 2+2?"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "gpt-4o"
    assert body["choices"][0]["message"]["content"] == "The answer is 4."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert calls["task"] == "Be terse.\n\nWhat is 2+2?"
    assert calls["cfg"].execution == "local"


def test_chat_completions_llm_model_override_swaps_model_not_wire_field(monkeypatch):
    calls = {}

    def _fake_run_task(task, cfg=None, **_kwargs):
        calls["cfg"] = cfg
        return [_FakeMessage("tool", "The answer is 4.")]

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "llm_model": "openai/gpt-4o",
            "llm_api_key": "sk-other",
        },
    )

    assert response.status_code == 200
    # The OpenAI wire field is still just echoed back...
    assert response.json()["model"] == "gpt-4o"
    # ...while the actual run used the llm_* override, not request.model.
    assert calls["cfg"].model == "openai/gpt-4o"
    assert calls["cfg"].api_key == "sk-other"


def test_chat_completions_llm_reasoning_effort_override(monkeypatch):
    calls = {}

    def _fake_run_task(task, cfg=None, **_kwargs):
        calls["cfg"] = cfg
        return [_FakeMessage("tool", "The answer is 4.")]

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "llm_reasoning_effort": "xhigh",
        },
    )

    assert response.status_code == 200
    assert calls["cfg"].reasoning_effort == "xhigh"
    assert calls["cfg"].model == "anthropic/claude-x"


def test_chat_completions_without_llm_override_keeps_configured_model(monkeypatch):
    calls = {}

    def _fake_run_task(task, cfg=None, **_kwargs):
        calls["cfg"] = cfg
        return [_FakeMessage("tool", "hi")]

    monkeypatch.setattr(server, "load_config", lambda: _cfg(model="anthropic/claude-x"))
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    client = TestClient(server.create_app())
    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert calls["cfg"].model == "anthropic/claude-x"


def test_chat_completions_without_user_message_returns_400(monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: _cfg())

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "system", "content": "context only"}]},
    )

    assert response.status_code == 400


def test_chat_completions_per_request_config_error_returns_400(monkeypatch):
    # Same reframing as the WS test above: load_config() itself succeeds at
    # startup; this covers a per-request config problem (an absolute
    # `project`, rejected by resolve_project_dir — ChatCompletionRequest
    # has no agents_md field to reuse the WS test's trigger) still
    # returning a clean 400 rather than an unhandled exception.
    monkeypatch.setattr(server, "load_config", lambda: _cfg())

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "project": "/etc/cron.d",
        },
    )

    assert response.status_code == 400
    assert "must be relative, not absolute" in response.json()["detail"]


def test_chat_completions_streaming_sends_sse_chunks(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        on_message(_FakeMessage("user", "echoed task, should not stream"))
        on_message(_FakeMessage("assistant", "step one"))
        # The real "finish" text arrives as a tool-role message (confirmed
        # live) — it must stream, unlike system/user echoes.
        on_message(_FakeMessage("tool", "step two"))

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "go"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]

    payloads = [line[len("data: ") :] for line in lines]
    assert payloads[-1] == "[DONE]"

    chunks = [json.loads(p) for p in payloads[:-1]]
    deltas = [c["choices"][0]["delta"] for c in chunks]

    assert deltas[0] == {"role": "assistant"}
    assert {"content": "step one"} in deltas
    assert {"content": "step two"} in deltas
    assert not any(d.get("content") == "echoed task, should not stream" for d in deltas)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def _summary():
    from certo.run_summary import ModelUsage, RunSummary

    return RunSummary(
        duration_seconds=5,
        models=(
            ModelUsage("openai/a", prompt_tokens=1000, completion_tokens=100),
            ModelUsage("openai/b", prompt_tokens=200, completion_tokens=20),
        ),
    )


def test_chat_completions_usage_counts_the_whole_run(monkeypatch):
    from types import SimpleNamespace

    from certo.runner import TaskResult

    def _fake_run_task(task, cfg=None, **_kwargs):
        outcome = SimpleNamespace(run_summary=_summary())
        return TaskResult([_FakeMessage("tool", "Done.")], outcome)

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    response = TestClient(server.create_app()).post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "go"}]},
    )

    assert response.json()["usage"] == {
        "prompt_tokens": 1200,
        "completion_tokens": 120,
        "total_tokens": 1320,
    }


def test_chat_completions_streaming_sends_usage_when_asked(monkeypatch):
    from types import SimpleNamespace

    def _fake_stream_task(task, cfg=None, on_message=None, **_kwargs):
        on_message(_FakeMessage("tool", "Done."))
        return SimpleNamespace(run_summary=_summary())

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    def chunks(body):
        with TestClient(server.create_app()).stream(
            "POST", "/v1/chat/completions", json=body
        ) as response:
            lines = [ln[len("data: ") :] for ln in response.iter_lines() if ln.startswith("data: ")]
        return [json.loads(p) for p in lines[:-1]]

    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "go"}], "stream": True}
    assert not any("usage" in c for c in chunks(body))

    last = chunks({**body, "stream_options": {"include_usage": True}})[-1]
    assert last["choices"] == []
    assert last["usage"] == {"prompt_tokens": 1200, "completion_tokens": 120, "total_tokens": 1320}


# --- escalate -------------------------------------------------------------------------

_LADDER_CATALOG = """
models:
  - name: local
    model: ollama/qwen
    base_url: http://localhost:11434
    ratings: {code: 2, cost: 5}
  - name: cloud
    model: openai/luna
    api_key: k
    ratings: {code: 5, cost: 2}
escalation:
  ladders:
    default: [{model: local}, {model: cloud}]
    cloud-only: [{model: cloud}]
"""


def _escalation_app(monkeypatch, tmp_path, calls):
    from model_file_helpers import model_file_config

    files = model_file_config(tmp_path, _LADDER_CATALOG)

    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **kwargs):
        calls.append({"cfg": cfg, **kwargs})
        return _fake_outcome()

    monkeypatch.setattr(
        server,
        "load_config",
        lambda: _cfg(**files),
    )
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)
    return TestClient(server.create_app())


@pytest.mark.parametrize(
    ("value", "ladder_name", "rungs"),
    [
        (True, "default", ["local", "cloud"]),
        ("cloud-only", "cloud-only", ["cloud"]),
    ],
)
def test_create_task_with_escalate(monkeypatch, tmp_path, value, ladder_name, rungs):
    calls: list = []
    client = _escalation_app(monkeypatch, tmp_path, calls)

    response = client.post("/tasks", json={"task": "do it", "escalate": value})
    _wait_for_status(client, response.json()["task_id"])

    assert calls[0]["cfg"].model_selection == "escalate"
    assert calls[0]["ladder"].name == ladder_name
    assert [r.name for r in calls[0]["ladder"].rungs] == rungs


def test_create_task_without_escalate_passes_no_ladder(monkeypatch, tmp_path):
    calls: list = []
    client = _escalation_app(monkeypatch, tmp_path, calls)

    response = client.post("/tasks", json={"task": "do it", "escalate": False})
    _wait_for_status(client, response.json()["task_id"])

    assert calls[0]["ladder"] is None
    assert calls[0]["cfg"].model_selection == "manual"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"escalate": True, "model": "openai/x"}, "can't be combined with model"),
        ({"escalate": "fast"}, "no escalation ladder named 'fast'"),
    ],
)
def test_create_task_escalate_errors_are_400(monkeypatch, tmp_path, payload, message):
    calls: list = []
    client = _escalation_app(monkeypatch, tmp_path, calls)

    response = client.post("/tasks", json={"task": "do it", **payload})

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert calls == []


def test_create_task_escalate_without_a_catalog_is_400(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    client = TestClient(server.create_app())

    response = client.post("/tasks", json={"task": "do it", "escalate": True})

    assert response.status_code == 400
    assert "No models_list.yaml found" in response.json()["detail"]


def test_websocket_with_escalate(monkeypatch, tmp_path):
    calls: list = []
    client = _escalation_app(monkeypatch, tmp_path, calls)

    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do it", "escalate": "cloud-only"})
        while ws.receive_json()["type"] != "result":
            pass

    assert [r.name for r in calls[0]["ladder"].rungs] == ["cloud"]


def _escalated_outcome():
    from dataclasses import replace

    from certo.escalation import RungResult

    return replace(
        _fake_outcome(),
        rungs=(
            RungResult(1, "local", "ollama/qwen", "no_progress", 1, 5.0, None),
            RungResult(2, "cloud", "openai/luna", "verified", 0, 3.0, None),
        ),
        final_rung=2,
    )


def test_get_task_returns_the_rungs(monkeypatch, tmp_path):
    calls: list = []
    client = _escalation_app(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(server, "stream_task", lambda *a, **k: _escalated_outcome())
    client = TestClient(server.create_app())

    response = client.post("/tasks", json={"task": "do it", "escalate": True})
    body = _wait_for_status(client, response.json()["task_id"])

    assert [(r["name"], r["verdict"], r["final"]) for r in body["rungs"]] == [
        ("local", "no_progress", False),
        ("cloud", "verified", True),
    ]
    assert body["rungs"][0]["fix_attempts"] == 1


def test_a_single_model_task_has_no_rungs(monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", lambda *a, **k: _fake_outcome())
    client = TestClient(server.create_app())

    body = _wait_for_status(client, client.post("/tasks", json={"task": "x"}).json()["task_id"])
    assert body["rungs"] is None


def test_websocket_result_includes_the_rungs(monkeypatch, tmp_path):
    calls: list = []
    _escalation_app(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(server, "stream_task", lambda *a, **k: _escalated_outcome())
    client = TestClient(server.create_app())

    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do it", "escalate": True})
        while (item := ws.receive_json())["type"] != "result":
            pass

    assert [r["name"] for r in item["rungs"]] == ["local", "cloud"]


# --- run records are filed under the request's project ----------------------


def test_stream_files_its_run_records_under_the_project(monkeypatch, tmp_path):
    calls = {}

    def _fake_stream_task(task, cfg=None, on_message=None, **kwargs):
        calls["project"] = kwargs.get("project")
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something", "project": "my-api"})
        ws.receive_json()

    assert calls["project"] == "my-api"


def test_chat_completions_files_its_run_records_under_the_project(monkeypatch, tmp_path):
    calls = {}

    def _fake_run_task(task, cfg=None, **kwargs):
        calls["project"] = kwargs.get("project")
        return [_FakeMessage("tool", "done")]

    monkeypatch.setattr(server, "load_config", lambda: _cfg(projects_dir=str(tmp_path)))
    monkeypatch.setattr(server, "run_task", _fake_run_task)

    client = TestClient(server.create_app())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "project": "my-api"},
    )

    assert response.status_code == 200
    assert calls["project"] == "my-api"


# --- the JSON result (result.py), as `certo --json` prints it ---------------


def test_get_task_returns_the_json_result(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome(verification_state="retry_exhausted", limitations=["pytest: 1 failed"])

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    final = _wait_for_status(client, task_id)

    result = final["result"]
    assert result["result_version"] == 1
    assert result["task"] == "do something"
    assert result["verdict"] == "retry_exhausted"
    assert result["limitations"] == ["pytest: 1 failed"]
    assert "key" not in str(result).replace("cache_read_tokens", "")


def test_get_task_result_says_why_a_run_failed(monkeypatch):
    def _fake_stream_task(task, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    task_id = client.post("/tasks", json={"task": "do something"}).json()["task_id"]
    final = _wait_for_status(client, task_id)

    assert final["result"]["verdict"] is None
    assert final["result"]["error"] == "provider down"


def test_stream_result_event_carries_the_json_result(monkeypatch):
    def _fake_stream_task(task, cfg=None, on_message=None, acceptance_checks=None, **_kwargs):
        return _fake_outcome()

    monkeypatch.setattr(server, "load_config", lambda: _cfg())
    monkeypatch.setattr(server, "stream_task", _fake_stream_task)

    client = TestClient(server.create_app())
    with client.websocket_connect("/tasks/stream") as ws:
        ws.send_json({"task": "do something"})
        event = ws.receive_json()

    assert event["type"] == "result"
    assert event["result"]["verdict"] == event["verification_state"]
