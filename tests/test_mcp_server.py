"""`certo mcp`: the tools, called through the `mcp` package's own client
connected in process. No LLM: runs, verify and check are fakes."""

from __future__ import annotations

import json
import time

import anyio
import pytest
from mcp import Client

from certo.config import Config
from certo.mcp_server import Folders, build_server
from certo.runner import CompletionContract, TaskOutcome
from certo.runs import RunManager
from certo.verification import CheckOutcome, VerificationRun


def _cfg(tmp_path, **overrides) -> Config:
    base = {
        "model": "openai/gpt-4o",
        "api_key": "sk-secret-key-value",
        "base_url": None,
        "workspace": str(tmp_path / "ws"),
        "projects_dir": str(tmp_path / "projects"),
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


def _outcome() -> TaskOutcome:
    contract = CompletionContract(
        goal="", acceptance_criteria=[], verification_checks=[], limitations=[]
    )
    return TaskOutcome(verification_state="verified", completion_contract=contract)


def _server(tmp_path, *, roots=(), stream=None, verify=None, check=None):
    load = lambda: _cfg(tmp_path)  # noqa: E731
    manager = RunManager(load=load, stream=stream or (lambda task, **_k: _outcome()))
    folders = Folders(str(tmp_path / "projects"), [str(r) for r in roots])
    return build_server(manager, folders, load=load, verify_fn=verify, check_fn=check)


def _call(server, name, arguments=None):
    """Call one tool; returns (is_error, the JSON value or the error text)."""

    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, arguments or {})

    result = anyio.run(go)
    text = result.content[0].text if result.content else ""
    if result.is_error:
        return True, text
    if result.structured_content is not None:
        value = result.structured_content
        return False, value.get("result", value) if set(value) == {"result"} else value
    return False, json.loads(text)


def _tools(server):
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    return anyio.run(go)


def test_the_core_tools_are_listed_with_their_hints(tmp_path):
    tools = {t.name: t for t in _tools(_server(tmp_path))}
    assert set(tools) == {
        "run_task",
        "run_status",
        "run_events",
        "run_cancel",
        "list_runs",
        "verify",
        "check_model",
    }
    assert tools["run_task"].annotations.destructive_hint is True
    assert tools["run_status"].annotations.read_only_hint is True
    assert tools["run_events"].annotations.read_only_hint is True


def test_run_task_returns_a_run_id_and_status_gives_the_result(tmp_path):
    server = _server(tmp_path)
    error, started = _call(server, "run_task", {"task": "do it", "project": "demo"})
    assert not error, started
    assert started["state"] in ("running", "finished")
    assert started["workspace"] == str((tmp_path / "projects" / "demo").resolve())

    for _ in range(100):
        error, status = _call(server, "run_status", {"run_id": started["run_id"]})
        if status["state"] != "running":
            break
        time.sleep(0.02)
    assert status["state"] == "finished"
    assert status["verdict"] == "verified"
    assert status["result"]["result_version"] == 1
    assert "sk-secret-key-value" not in json.dumps(status)


def test_run_task_needs_a_project_or_a_folder(tmp_path):
    error, text = _call(_server(tmp_path), "run_task", {"task": "do it"})
    assert error
    assert "say where to work" in text


def test_a_folder_outside_the_roots_is_refused(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    root = tmp_path / "code"
    root.mkdir()
    error, text = _call(
        _server(tmp_path, roots=[root]), "run_task", {"task": "x", "folder": str(outside)}
    )
    assert error
    assert "outside the folders this server may use" in text


def test_a_folder_inside_a_root_is_used(tmp_path):
    root = tmp_path / "code"
    (root / "app").mkdir(parents=True)
    error, started = _call(
        _server(tmp_path, roots=[root]), "run_task", {"task": "x", "folder": str(root / "app")}
    )
    assert not error, started
    assert started["workspace"] == str((root / "app").resolve())


def test_a_relative_folder_is_refused(tmp_path):
    error, text = _call(_server(tmp_path), "run_task", {"task": "x", "folder": "app"})
    assert error
    assert "full path" in text


def test_an_unknown_run_is_an_error(tmp_path):
    error, text = _call(_server(tmp_path), "run_status", {"run_id": "nope"})
    assert error
    assert "no run with id" in text


def test_verify_runs_the_checks_on_a_project(tmp_path):
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    check = CheckOutcome("pytest", "pytest -q", True, "passed", 0, "/p", "3 passed", "3 passed")
    seen = []

    def verify(path):
        seen.append(path)
        return VerificationRun(checks=[check])

    error, result = _call(_server(tmp_path, verify=verify), "verify", {"project": "demo"})
    assert not error, result
    assert result["verdict"] == "verified"
    assert result["checks"][0]["name"] == "pytest"
    assert seen == [str((tmp_path / "projects" / "demo"))]


def test_check_model_returns_the_check_without_the_key(tmp_path):
    from certo.llm_check import LLMCheckResult

    def check(cfg):
        return LLMCheckResult(ok=True, model=cfg.model, base_url=None, latency_seconds=1.2)

    error, result = _call(_server(tmp_path, check=check), "check_model", {})
    assert not error, result
    assert result["ok"] is True
    assert result["model"] == "openai/gpt-4o"
    assert "sk-secret-key-value" not in json.dumps(result)


@pytest.mark.parametrize("argv", [["--root", "/no/such/folder"]])
def test_a_root_that_isnt_a_folder_is_refused(argv, capsys):
    from certo.mcp_server import mcp_main

    assert mcp_main(argv) == 1
    assert "is not a folder" in capsys.readouterr().err


def _read(server, uri):
    async def go():
        async with Client(server) as client:
            return await client.read_resource(uri)

    return anyio.run(go)


def test_a_projects_status_and_runs_are_resources(tmp_path):
    server = _server(tmp_path)

    async def templates():
        async with Client(server) as client:
            return (await client.list_resource_templates()).resource_templates

    assert {t.uri_template for t in anyio.run(templates)} == {
        "certo://projects/{name}/status",
        "certo://projects/{name}/runs",
    }
    state = tmp_path / "projects" / "demo" / ".certo"
    state.mkdir(parents=True)
    (state / "STATUS.md").write_text("# Status\nverified\n")
    (state / "RUNS.md").write_text("# Runs\n")
    assert "verified" in _read(server, "certo://projects/demo/status").contents[0].text
    assert _read(server, "certo://projects/demo/runs").contents[0].text == "# Runs\n"


def test_a_project_with_no_status_yet_is_not_found(tmp_path):
    from mcp.shared.exceptions import MCPError

    with pytest.raises(BaseException) as caught:
        _read(_server(tmp_path), "certo://projects/new/status")
    errors = [caught.value]
    while isinstance(errors[-1], BaseExceptionGroup):
        errors.append(errors[-1].exceptions[0])
    assert isinstance(errors[-1], MCPError)
    assert "no STATUS.md yet" in str(errors[-1])
