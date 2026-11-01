"""`certo mcp`: the tools, called through the `mcp` package's own client
connected in process. No LLM: runs, verify and check are fakes."""

from __future__ import annotations

import json
import shutil
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
        "run_resume",
        "list_runs",
        "checkpoints",
        "rollback",
        "verify",
        "check_model",
        "list_projects",
        "list_models",
        "list_skills",
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

    server = _server(tmp_path, verify=verify)
    error, started = _call(server, "verify", {"project": "demo"})
    assert not error, started
    result = _wait_done(server, started["run_id"])["result"]
    assert result["verdict"] == "verified"
    assert result["checks"][0]["name"] == "pytest"
    assert result["task"] == "certo verify"
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


def _wait_done(server, run_id):
    for _ in range(200):
        error, status = _call(server, "run_status", {"run_id": run_id})
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the run didn't end")


def test_run_resume_with_nothing_saved_is_an_error(tmp_path):
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    error, text = _call(_server(tmp_path), "run_resume", {"project": "demo"})
    assert error
    assert "nothing to resume" in text


def test_run_resume_continues_the_saved_run(tmp_path):
    from certo.project_state import RunRecord, save_record

    workspace = tmp_path / "projects" / "demo"
    workspace.mkdir(parents=True)
    save_record(
        str(workspace),
        RunRecord(
            task="the old task",
            conversation_id="c",
            model="m",
            execution="local",
            started_at="",
            updated_at="",
            status="interrupted",
        ),
    )
    seen = {}

    def stream(task, *, resume_from, resume_instruction, **_kwargs):
        seen.update(task=task, resumed=resume_from.task, extra=resume_instruction)
        return _outcome()

    server = _server(tmp_path, stream=stream)
    error, started = _call(server, "run_resume", {"project": "demo", "instruction": "use tabs"})
    assert not error, started
    assert started["task"] == "the old task"
    assert _wait_done(server, started["run_id"])["verdict"] == "verified"
    assert seen == {"task": "the old task", "resumed": "the old task", "extra": "use tabs"}


def test_run_resume_when_the_last_run_was_verified_has_nothing_to_do(tmp_path):
    from certo.project_state import RunRecord, save_record

    workspace = tmp_path / "projects" / "demo"
    workspace.mkdir(parents=True)
    save_record(
        str(workspace),
        RunRecord(
            task="t",
            conversation_id="c",
            model="m",
            execution="local",
            started_at="",
            updated_at="",
            status="finished",
            verdict="verified",
        ),
    )
    error, result = _call(_server(tmp_path), "run_resume", {"project": "demo"})
    assert not error, result
    assert result["state"] == "nothing_to_do"
    assert result["run_id"] is None


def test_a_milestones_file_runs_each_milestone_in_order(tmp_path):
    plan = tmp_path / "projects" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# App\n\n## Milestone 1: first\nDo a.\n\n## Milestone 2: second\nDo b.\n")
    tasks = []

    def stream(task, **_kwargs):
        tasks.append(task)
        return _outcome()

    server = _server(tmp_path, stream=stream)
    error, started = _call(
        server,
        "run_task",
        {"task": "", "project": "demo", "milestones_file": str(plan)},
    )
    assert not error, started
    status = _wait_done(server, started["run_id"])
    assert status["verdict"] == "verified"
    assert [m["verdict"] for m in status["result"]["milestones"]] == ["verified", "verified"]
    assert len(tasks) == 2
    assert "Do a." in tasks[0] and "Do b." in tasks[1]
    _, events = _call(server, "run_events", {"run_id": started["run_id"]})
    assert any("Milestone 2 of 2: verified" in e["text"] for e in events["events"])


def test_a_milestones_file_outside_the_folders_is_refused(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("## Milestone 1: a\nDo a.\n")
    error, text = _call(
        _server(tmp_path),
        "run_task",
        {"task": "", "project": "demo", "milestones_file": str(plan)},
    )
    assert error
    assert "outside the folders" in text


def test_run_task_can_ask_for_independent_tests(tmp_path):
    seen = {}

    def stream(task, *, cfg, **_kwargs):
        seen.update(on=cfg.independent_tests, strict=cfg.independent_tests_strict)
        return _outcome()

    server = _server(tmp_path, stream=stream)
    error, started = _call(
        server, "run_task", {"task": "x", "project": "demo", "independent_tests": True}
    )
    assert not error, started
    _wait_done(server, started["run_id"])
    assert seen == {"on": True, "strict": False}


# --- checkpoints and rollback (real git, as tests/test_checkpoints.py) -------


def _project_with_checkpoints(tmp_path):
    from certo.checkpoints import snapshot

    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "a.py").write_text("one\n")
    snapshot(str(project), "first", always=True)
    (project / "a.py").write_text("two\n")
    (project / "b.py").write_text("new\n")
    snapshot(str(project), "second", always=True)
    return project


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_checkpoints_are_listed(tmp_path):
    _project_with_checkpoints(tmp_path)
    error, result = _call(_server(tmp_path), "checkpoints", {"project": "demo"})
    assert not error, result
    assert [(c["number"], c["label"]) for c in result["checkpoints"]] == [
        (1, "first"),
        (2, "second"),
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_rollback_without_confirm_only_says_what_would_change(tmp_path):
    project = _project_with_checkpoints(tmp_path)
    error, result = _call(_server(tmp_path), "rollback", {"project": "demo", "number": 1})
    assert not error, result
    assert result["rolled_back"] is False
    assert {(c["change"], c["path"]) for c in result["changes"]} == {
        ("restored", "a.py"),
        ("deleted", "b.py"),
    }
    assert (project / "a.py").read_text() == "two\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_rollback_with_confirm_restores_and_can_be_undone(tmp_path):
    project = _project_with_checkpoints(tmp_path)
    server = _server(tmp_path)
    error, result = _call(server, "rollback", {"project": "demo", "number": 1, "confirm": True})
    assert not error, result
    assert result["rolled_back"] is True
    assert (project / "a.py").read_text() == "one\n"
    assert not (project / "b.py").exists()

    error, undone = _call(
        server, "rollback", {"project": "demo", "number": result["undo_with"], "confirm": True}
    )
    assert not error, undone
    assert (project / "a.py").read_text() == "two\n"
    assert (project / "b.py").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_rollback_is_refused_while_a_run_works_there(tmp_path):
    import threading

    _project_with_checkpoints(tmp_path)
    release = threading.Event()

    def stream(task, **_kwargs):
        release.wait(5)
        return _outcome()

    server = _server(tmp_path, stream=stream)
    _call(server, "run_task", {"task": "x", "project": "demo"})
    error, text = _call(server, "rollback", {"project": "demo", "number": 1, "confirm": True})
    release.set()
    assert error
    assert "is working in" in text


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_rollback_to_a_number_that_doesnt_exist_is_refused(tmp_path):
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    error, text = _call(_server(tmp_path), "rollback", {"project": "demo", "number": 3})
    assert error
    assert "no checkpoint 3" in text


def test_every_command_has_a_tool_or_says_why_not(tmp_path):
    import re
    from pathlib import Path

    from certo.mcp_server import COMMAND_TOOLS, NO_TOOL

    commands_md = Path(__file__).resolve().parent.parent / "docs/reference/commands.md"
    documented = set(re.findall(r"^#{2,3} `(certo[^`]*)`", commands_md.read_text(), re.M))
    assert documented == set(COMMAND_TOOLS) | set(NO_TOOL)
    assert not set(COMMAND_TOOLS) & set(NO_TOOL)
    tools = {t.name for t in _tools(_server(tmp_path))}
    for command, names in COMMAND_TOOLS.items():
        assert set(names) <= tools, command


def test_list_projects_gives_each_projects_last_run(tmp_path):
    from certo.project_state import RunRecord, save_record

    projects = tmp_path / "projects"
    (projects / "fresh").mkdir(parents=True)
    (projects / "done").mkdir()
    (projects / ".hidden").mkdir()
    save_record(
        str(projects / "done"),
        RunRecord(
            task="Write fib",
            conversation_id="c" * 32,
            model="anthropic/claude-haiku-5-5",
            execution="local",
            started_at="2026-11-01T10:00:00+00:00",
            updated_at="2026-11-01T10:01:00+00:00",
            status="finished",
            verdict="verified",
        ),
    )
    is_error, value = _call(_server(tmp_path), "list_projects")
    assert not is_error
    by_name = {p["name"]: p for p in value["projects"]}
    assert list(by_name) == ["done", "fresh"]
    last = dict(by_name["done"]["last_run"])
    assert last.pop("updated_at")  # saving stamps the time
    assert last == {
        "task": "Write fib",
        "status": "finished",
        "verdict": "verified",
        "model": "anthropic/claude-haiku-5-5",
    }
    assert by_name["fresh"]["last_run"] is None
    assert by_name["fresh"]["running"] is None


def _model_files(tmp_path):
    files = tmp_path / "models"
    files.mkdir()
    (files / "models_list.yaml").write_text(
        "models:\n"
        "  - name: cheap\n    model: openai/gpt-6-luna\n"
        "    ratings: {reasoning: 3, precision: 3, code: 3, cost: 4}\n"
        "  - name: strong\n    model: anthropic/claude-sonnet-5-5\n"
        "    ratings: {reasoning: 4, precision: 4, code: 5, cost: 2}\n"
        "  - name: unused\n    model: anthropic/claude-opus-5-5\n"
    )
    (files / "models.yaml").write_text(
        "models:\n  - name: cheap\n    api_key: sk-in-models-yaml\n  - name: strong\n"
    )
    (files / "escalation.yaml").write_text(
        "escalation:\n  ladders:\n    climb:\n      rungs:\n"
        "        - model: cheap\n        - model: strong\n"
    )
    return files


def test_list_models_shows_the_models_and_ladders_never_a_key(tmp_path, monkeypatch):
    files = _model_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    load = lambda: _cfg(  # noqa: E731
        tmp_path,
        models_file=str(files / "models.yaml"),
        models_list_file=str(files / "models_list.yaml"),
        escalation_file=str(files / "escalation.yaml"),
    )
    manager = RunManager(load=load, stream=lambda task, **_k: _outcome())
    server = build_server(manager, Folders(str(tmp_path / "projects"), []), load=load)
    is_error, value = _call(server, "list_models")
    assert not is_error
    assert value["configured_model"] == "openai/gpt-4o"
    assert [(m["name"], m["model"], m["active"]) for m in value["models"]] == [
        ("cheap", "openai/gpt-6-luna", True),
        ("strong", "anthropic/claude-sonnet-5-5", True),
    ]
    assert value["ladders"] == [{"name": "climb", "rungs": ["cheap", "strong"]}]
    assert value["files"]["escalation"] == str(files / "escalation.yaml")
    text = json.dumps(value)
    assert "sk-in-models-yaml" not in text and "sk-secret-key-value" not in text


def test_list_models_without_model_files_says_how_to_add_them(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    is_error, value = _call(_server(tmp_path), "list_models")
    assert not is_error
    assert value["configured_model"] == "openai/gpt-4o"
    assert value["files"] is None
    assert "certo init models" in value["message"]


def test_list_skills_lists_official_and_project_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    skill = tmp_path / "projects" / "demo" / ".certo" / "skills" / "house-style"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: house-style\ndescription: Our code style.\n"
        "triggers:\n  - style\n---\nUse tabs.\n"
    )
    server = _server(tmp_path)
    is_error, value = _call(server, "list_skills")
    assert not is_error
    layers = {s["layer"] for s in value["skills"]}
    assert layers == {"official"}
    assert "for_task" not in value

    is_error, value = _call(
        server, "list_skills", {"project": "demo", "task": "Fix the style of main.py"}
    )
    assert not is_error, value
    mine = [s for s in value["skills"] if s["name"] == "house-style"]
    assert mine and mine[0]["layer"] == "project" and mine[0]["state"] == "on"
    assert {"name": "house-style", "layer": "project"}.items() <= next(
        r for r in value["for_task"]["now"] if r["name"] == "house-style"
    ).items()


def test_list_skills_for_a_project_that_doesnt_exist_is_refused(tmp_path):
    is_error, text = _call(_server(tmp_path), "list_skills", {"project": "nope"})
    assert is_error and "doesn't exist" in text
