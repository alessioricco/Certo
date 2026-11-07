"""`certo mcp`: Certo as an MCP server over stdio, so an editor or an agent can
run tasks and get Certo's verdict (DECISIONS.md: "The MCP server: every
command, on a shared core", "The MCP server is `certo mcp`, over stdio, with
no authentication", "The MCP server uses no deprecated MCP feature").

The tools sit on the shared core: `runs.RunManager` for runs, `api` for the
settings, `result` for the JSON result. A tool works only in a project under
`CERTO_PROJECTS_DIR` (by name) or in a folder inside one of the `--root`
folders given at start; nothing else is reachable.

While serving, the `mcp` package points stdout's file descriptor at stderr,
so the agent's printed steps and the checks' output never reach the protocol.
"""

from __future__ import annotations

import argparse
import functools
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any

from .api import RunOptions, UsageError, resolve_config
from .config import Config, ConfigError, defer_llm_check, load_config
from .runs import RunManager

# Every command in docs/reference/commands.md, and the tools that do its work
# over MCP (tests/test_mcp_server.py checks that the list is complete).
COMMAND_TOOLS: dict[str, tuple[str, ...]] = {
    "certo": ("run_task", "run_resume", "run_status", "run_events", "run_cancel", "list_runs"),
    "certo verify": ("verify",),
    "certo check": ("check_model", "list_models"),
    "certo models": ("list_models",),
    "certo skills": ("list_skills",),
    "certo skills list": ("list_skills",),
    "certo checkpoints": ("checkpoints",),
    "certo rollback": ("rollback",),
}

# The commands with no tool, and why. Those that say "on request" get a
# tool when someone asks (TODO.md); the others never do (DECISIONS.md).
NO_TOOL: dict[str, str] = {
    "certo init": "asks questions and writes your settings file: run it in a terminal",
    "certo init models": "asks questions and writes your model files: run it in a terminal",
    "certo models update": "asks about each change to your models list: run it in a terminal",
    "certo models check": "a maintenance check of your models list's prices: on request",
    "certo skills add": (
        "from git it downloads code, with a license only a person may accept: run it in a "
        "terminal; a skill file or folder of yours: on request"
    ),
    "certo skills remove": "changes the skills every run gets: on request",
    "certo skills enable": "turns on downloaded code, a person's decision: run it in a terminal",
    "certo skills disable": "changes the skills every run gets: on request",
    "certo skills update": "downloads code, with a license only a person may accept: run it in a terminal",
    "certo skills sync": "downloads code, with a license only a person may accept: run it in a terminal",
    "certo skills suggest": "reads only; a tool on request",
    "certo skills assess": (
        "downloads code from repositories a person chose to trust: run it in a terminal"
    ),
    "certo bench": "runs for hours, and is set up and read in a terminal",
    "certo mcp": "it is this server",
    "certo-server": "another server, over HTTP",
    "certo-admin": "manages certo-server's task store, not this server's runs",
    "certo-admin list": "manages certo-server's task store, not this server's runs",
    "certo-admin show": "manages certo-server's task store, not this server's runs",
    "certo-admin delete-task": "manages certo-server's task store, not this server's runs",
    "certo-admin delete-project": "manages certo-server's task store, not this server's runs",
    "certo-admin purge": "manages certo-server's task store, not this server's runs",
    "certo-admin check-llm": "certo-server's model check; check_model does the same here",
}

INSTRUCTIONS = (
    "Certo runs a coding task with an agent, then checks the result itself: it runs the "
    "project's tests and checks and gives a verdict (verified, or why not). Start a task "
    "with run_task, follow it with run_status and run_events, stop it with run_cancel, "
    "and continue a stopped or failed one with run_resume. "
    "verify checks a folder without an agent. list_projects, list_models and list_skills "
    "show what there is to work with. Work happens only in a named project "
    "(project) or in a folder the server was started with (folder). A project's "
    "certo://projects/NAME/status and certo://projects/NAME/runs resources hold its last "
    "run's status and its run history."
)


def _user_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Certo's own errors (a wrong setting, options that don't go together,
    an unknown run) reach the client with their message; the `mcp` package
    hides the message of any other exception."""
    from mcp.server.mcpserver.exceptions import ToolError

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:  # ConfigError, UsageError, AcceptanceCheckError
            raise ToolError(str(exc)) from exc

    return wrapper


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class Folders:
    """Where the tools may work: projects under `projects_dir`, by name, and
    folders inside `roots` (and `projects_dir`), by path."""

    def __init__(self, projects_dir: str, roots: Sequence[str]) -> None:
        self.projects_dir = os.path.realpath(projects_dir)
        self.roots = [os.path.realpath(r) for r in roots]

    def options(self, project: str | None, folder: str | None) -> dict[str, Any]:
        """The `RunOptions` fields for a tool's `project` or `folder`."""
        if project is not None and folder is not None:
            raise UsageError("give project or folder, not both")
        if project is not None:
            return {"project": project}
        if folder is None:
            raise UsageError(
                "say where to work: project (a name under the projects folder) or folder "
                "(a path inside a --root folder)"
            )
        path = os.path.realpath(folder)
        if not os.path.isabs(folder) or not os.path.isdir(path):
            raise UsageError(f"folder must be the full path of an existing folder: {folder!r}")
        allowed = [self.projects_dir, *self.roots]
        if not any(_inside(path, root) for root in allowed):
            raise UsageError(
                f"{folder} is outside the folders this server may use: " + ", ".join(allowed)
            )
        return {"workspace": path}

    def file(self, path: str) -> str:
        """A file a tool reads (a milestones task file): a full path inside
        the same folders."""
        real = os.path.realpath(path)
        if not os.path.isabs(path) or not os.path.isfile(real):
            raise UsageError(f"milestones_file must be the full path of an existing file: {path!r}")
        allowed = [self.projects_dir, *self.roots]
        if not any(_inside(real, root) for root in allowed):
            raise UsageError(
                f"{path} is outside the folders this server may use: " + ", ".join(allowed)
            )
        return real


def build_server(
    manager: RunManager,
    folders: Folders,
    *,
    load: Callable[[], Config],
    verify_fn: Callable[[str], Any] | None = None,
    check_fn: Callable[[Config], Any] | None = None,
):
    """The MCP server with the core tools. `verify_fn` and `check_fn` are for tests."""
    from mcp.server.mcpserver import MCPServer
    from mcp_types import ToolAnnotations

    from . import __version__

    server = MCPServer("certo", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        annotations=ToolAnnotations(
            title="Run a task",
            readOnlyHint=False,
            destructiveHint=True,
            openWorldHint=True,
        )
    )
    @_user_errors
    def run_task(
        task: str,
        project: str | None = None,
        folder: str | None = None,
        model: str | None = None,
        escalate: str | None = None,
        acceptance_checks: list[dict[str, Any]] | None = None,
        milestones_file: str | None = None,
        independent_tests: bool = False,
        independent_tests_strict: bool = False,
    ) -> dict[str, Any]:
        """Start a coding task: an agent works in the project, then Certo runs the
        project's checks and gives a verdict. Returns at once with a run_id; follow it
        with run_status and run_events. `project` is a project name (created if new)
        under Certo's projects folder; `folder` is the full path of a folder inside one
        the server allows. `model` overrides the configured model; `escalate` climbs a
        ladder of models ("" for the default ladder). `acceptance_checks` are extra file
        checks, as in `certo --acceptance-checks`. `milestones_file` is the full path of
        a task file split by `## Milestone N: title` headings, as in `certo --milestones`:
        each milestone runs and is verified before the next starts, and `task` is then
        ignored. `independent_tests` first has tests written from the task alone, by a
        separate conversation, and runs them on the result: they report whether the
        agent's own tests could have fooled Certo; with `independent_tests_strict`, a
        `verified` run whose independent tests mostly fail ends `independent_failed`.
        The agent can change any file in the folder and run commands there."""
        from .acceptance import parse_acceptance_checks

        options = RunOptions(
            model=model,
            escalate=escalate,
            independent_tests=True if independent_tests else None,
            independent_tests_strict=independent_tests_strict,
            **folders.options(project, folder),
        )
        checks = parse_acceptance_checks(acceptance_checks) if acceptance_checks else None
        source = folders.file(milestones_file) if milestones_file is not None else None
        run = manager.start(task, options, acceptance_checks=checks, milestones_file=source)
        return _started(run)

    @server.tool(
        annotations=ToolAnnotations(
            title="Continue a run",
            readOnlyHint=False,
            destructiveHint=True,
            openWorldHint=True,
        )
    )
    @_user_errors
    def run_resume(
        project: str | None = None,
        folder: str | None = None,
        instruction: str | None = None,
        model: str | None = None,
        escalate: str | None = None,
    ) -> dict[str, Any]:
        """Continue the last run in a project or folder, as `certo --resume` does: one
        that was cancelled, stopped with an error, or ended without `verified`, from
        where it stopped. After a milestones run, it continues the first milestone not
        verified, then the rest. `instruction` is sent to the agent as an extra message.
        Returns a run_id like run_task, or state `nothing_to_do` when everything there
        is already verified."""
        from .api import NothingToDo

        options = RunOptions(model=model, escalate=escalate, **folders.options(project, folder))
        try:
            run = manager.start(instruction, options, resume=True)
        except NothingToDo as exc:
            return {"run_id": None, "state": "nothing_to_do", "message": str(exc)}
        return _started(run)

    def _started(run: Any) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "state": run.state,
            "task": run.task,
            "project": run.project,
            "workspace": run.workspace,
        }

    @server.tool(annotations=ToolAnnotations(title="A run's status", readOnlyHint=True))
    @_user_errors
    def run_status(run_id: str) -> dict[str, Any]:
        """A run's state (running, finished, cancelled or error) and, once it ended,
        its result: the verdict, the checks with the end of their output, the
        acceptance checks, and the time, tokens and cost."""
        return manager.status(run_id)

    @server.tool(annotations=ToolAnnotations(title="A run's events", readOnlyHint=True))
    @_user_errors
    def run_events(run_id: str, since: int = 0) -> dict[str, Any]:
        """What happened in a run so far: the agent's messages and Certo's notices,
        numbered. Pass the `next` value of the last call as `since` to get only the
        new ones."""
        return manager.events(run_id, since)

    @server.tool(
        annotations=ToolAnnotations(
            title="Cancel a run", readOnlyHint=False, destructiveHint=False, idempotentHint=True
        )
    )
    @_user_errors
    def run_cancel(run_id: str) -> dict[str, Any]:
        """Stop a run at the agent's next step. The work so far is kept, and the run
        can be continued later with `certo --resume` in its folder."""
        return manager.cancel(run_id)

    @server.tool(annotations=ToolAnnotations(title="List the runs", readOnlyHint=True))
    @_user_errors
    def list_runs() -> list[dict[str, Any]]:
        """The runs this server started, with their state and verdict."""
        return manager.list()

    @server.tool(
        annotations=ToolAnnotations(
            title="Verify a folder", readOnlyHint=False, destructiveHint=False
        )
    )
    @_user_errors
    def verify(project: str | None = None, folder: str | None = None) -> dict[str, Any]:
        """Run Certo's checks on a project without an agent, as `certo verify` does:
        its tests, build and linters where they are set up. It may create the
        project's own environment (.venv) to run them. Returns a run_id at once, like
        run_task; run_status then gives the verdict and each check."""
        run = manager.start_verify(RunOptions(**folders.options(project, folder)), verify=verify_fn)
        return _started(run)

    def _checkpoint_folder(project: str | None, folder: str | None) -> str:
        from .checkpoints import git_available

        cfg = resolve_config(RunOptions(**folders.options(project, folder)), load=load)
        path = os.path.abspath(cfg.workspace)
        if not os.path.isdir(path):
            raise UsageError(f"{path} doesn't exist")
        if not git_available():
            raise UsageError("checkpoints need git, which isn't installed")
        return path

    def _listed(checkpoint: Any) -> dict[str, Any]:
        return {"number": checkpoint.number, "label": checkpoint.label, "when": checkpoint.when}

    @server.tool(annotations=ToolAnnotations(title="List checkpoints", readOnlyHint=True))
    @_user_errors
    def checkpoints(project: str | None = None, folder: str | None = None) -> dict[str, Any]:
        """The snapshots Certo took of a project during its runs, as `certo
        checkpoints` lists them: number, label and time, oldest first. `rollback`
        takes a number from this list."""
        from .checkpoints import list_checkpoints

        path = _checkpoint_folder(project, folder)
        return {"workspace": path, "checkpoints": [_listed(c) for c in list_checkpoints(path)]}

    @server.tool(
        annotations=ToolAnnotations(
            title="Roll back to a checkpoint", readOnlyHint=False, destructiveHint=True
        )
    )
    @_user_errors
    def rollback(
        number: int,
        project: str | None = None,
        folder: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Put a project's files back as they were at checkpoint `number`, as `certo
        rollback` does. Without `confirm`, nothing changes: it returns the files a
        rollback would restore, add back or delete. With `confirm` true, it rolls back;
        the files as they were before become a checkpoint, so rolling back to that one
        undoes it. Refused while a run is working in the folder."""
        from .checkpoints import CheckpointError, changed_files, list_checkpoints
        from .checkpoints import rollback as roll_back

        path = _checkpoint_folder(project, folder)
        other = manager.busy(path)
        if other is not None:
            raise UsageError(f"run {other} is working in {path}: wait for it, or cancel it")
        found = list_checkpoints(path)
        if not 1 <= number <= len(found):
            raise UsageError(
                f"no checkpoint {number}; {path} has " + (f"1 to {len(found)}" if found else "none")
            )
        target = found[number - 1]
        words = {"M": "restored", "A": "added back", "D": "deleted"}
        try:
            changes = [
                {"change": words.get(kind[:1], kind), "path": name}
                for kind, _, name in (line.partition(" ") for line in changed_files(path, target))
            ]
            if not confirm or not changes:
                return {
                    "workspace": path,
                    "checkpoint": _listed(target),
                    "rolled_back": False,
                    "changes": changes,
                }
            before, after = roll_back(path, number)
        except CheckpointError as exc:
            raise UsageError(str(exc)) from exc
        undo = before.number if before is not None else found[-1].number
        return {
            "workspace": path,
            "checkpoint": _listed(target),
            "rolled_back": True,
            "changes": changes,
            "undo_with": undo,
        }

    def _settings() -> Config:
        # These tools need no model: one given to a run comes later.
        with defer_llm_check():
            return load()

    @server.tool(annotations=ToolAnnotations(title="List the projects", readOnlyHint=True))
    @_user_errors
    def list_projects() -> dict[str, Any]:
        """The projects under Certo's projects folder, by name, each with its last
        run as Certo saved it (task, status, verdict, model, time; null when it has
        none) and the id of a run of this server working there now."""
        from .project_state import load_record

        root = folders.projects_dir
        names = sorted(
            n
            for n in (os.listdir(root) if os.path.isdir(root) else [])
            if not n.startswith(".") and os.path.isdir(os.path.join(root, n))
        )
        projects = []
        for name in names:
            path = os.path.join(root, name)
            record = load_record(path)
            last = None
            if record is not None:
                last = {
                    "task": record.task,
                    "status": record.status,
                    "verdict": record.verdict,
                    "model": record.model,
                    "updated_at": record.updated_at,
                }
            projects.append(
                {"name": name, "path": path, "last_run": last, "running": manager.busy(path)}
            )
        return {"projects_dir": root, "projects": projects}

    @server.tool(annotations=ToolAnnotations(title="List the models", readOnlyHint=True))
    @_user_errors
    def list_models() -> dict[str, Any]:
        """The models Certo may use: the configured one, and, when the model files
        exist (models_list.yaml, models.yaml), each model with its id, whether it is
        active, its ratings and description, the ladders `escalate` takes by name,
        and the problems in the files. Never a key. `run_task`'s `model` takes a
        model id (a model's `model` here), with the key from Certo's settings;
        `escalate` takes a ladder's `name`."""
        from .catalog_check import check_catalog, usable_rungs
        from .escalation import EscalationError, derive_ladder
        from .model_catalog import load_model_catalog
        from .model_files import resolve, resolve_optional

        cfg = _settings()
        answer: dict[str, Any] = {"configured_model": cfg.model or None, "files": None}
        try:
            list_path, models_path = resolve(cfg.models_file, cfg.models_list_file)
        except ValueError as exc:
            answer["message"] = str(exc)
            return answer
        profiles_path, escalation_path = resolve_optional(
            cfg.task_profiles_file, cfg.escalation_file
        )
        catalog = load_model_catalog(
            list_path,
            models_path,
            profiles_path=profiles_path,
            escalation_path=escalation_path,
            strict=False,
        )
        report = check_catalog(catalog)
        try:
            derived = [r.name for r in derive_ladder(catalog).rungs]
        except EscalationError:
            derived = []
        answer.update(
            files={
                "list": list_path,
                "models": models_path,
                "task_profiles": profiles_path,
                "escalation": escalation_path,
            },
            models=[
                {
                    "name": m.name,
                    "model": m.model,
                    "active": m.activated,
                    "reasoning_effort": m.reasoning_effort,
                    "context_tokens": m.context_tokens or None,
                    "ratings": dict(m.ratings),
                    "description": m.description,
                    "missing_settings": list(m.missing_vars),
                }
                for m in catalog.models
                if m.configured
            ],
            ladders=[
                {"name": ladder.name, "rungs": [r.model for r in usable_rungs(ladder, catalog)]}
                for ladder in catalog.escalation.ladders.values()
            ],
            derived_ladder=derived,
            errors=list(report.errors),
            warnings=list(report.warnings),
        )
        return answer

    @server.tool(annotations=ToolAnnotations(title="List the skills", readOnlyHint=True))
    @_user_errors
    def list_skills(
        project: str | None = None, folder: str | None = None, task: str | None = None
    ) -> dict[str, Any]:
        """The skills a run gets, as `certo skills list` shows them: official ones
        (come with Certo), your global ones and, with `project` or `folder`, that
        project's own. Each says how it fires, its rough size in tokens, whether it
        is on, and what replaces it. With `task`, also which skills would go into a
        run of that task from its first message, and which may come in later."""
        from . import skill_library as lib

        cfg = _settings()
        workspace = None
        if project is not None or folder is not None:
            cfg = resolve_config(RunOptions(**folders.options(project, folder)), load=_settings)
            workspace = os.path.abspath(cfg.workspace)
            if not os.path.isdir(workspace):
                raise UsageError(f"{workspace} doesn't exist")
        found = lib.collect(cfg, workspace, project_name=project)
        answer: dict[str, Any] = {
            "skills": [
                {
                    "name": r.name,
                    "layer": r.layer,
                    "state": r.state,
                    "fires": lib.how_it_fires(r.skill) if r.skill is not None else None,
                    "tokens": lib.size_in_tokens(r.skill) if r.skill is not None else None,
                    "downloaded": r.downloaded,
                    "replaced_by": r.replaced_by,
                    "where": r.where,
                }
                for r in found.rows
            ]
        }
        if task is not None:
            active = [r for r in found.rows if r.active and r.skill is not None]
            answer["for_task"] = {
                "now": [
                    {"name": r.name, "layer": r.layer, "why": why}
                    for r in active
                    if (why := lib.fires_for_task(r.skill, task))
                ],
                "later": [
                    {"name": r.name, "layer": r.layer, "how": how}
                    for r in active
                    if (how := lib.later_for_task(r.skill))
                ],
            }
        return answer

    @server.tool(annotations=ToolAnnotations(title="Check the model", openWorldHint=True))
    @_user_errors
    def check_model(model: str | None = None) -> dict[str, Any]:
        """Make one small real call to the configured model (or `model`) and say
        whether it answers with a tool call, as Certo's agent needs, as `certo check`
        does. Returns how long it took, and the error and a hint when it failed."""
        from .llm_check import check_tool_calling

        cfg = resolve_config(RunOptions(model=model), load=load)
        result = (check_fn or check_tool_calling)(cfg)
        return asdict(result)

    def _project_file(name: str, path_of: Callable[[str], str], what: str) -> str:
        from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

        from .config import resolve_project_dir

        try:
            workspace = resolve_project_dir(folders.projects_dir, name)
        except ValueError as exc:
            raise ResourceError(str(exc)) from exc
        path = path_of(workspace)
        if not os.path.isfile(path):
            raise ResourceNotFoundError(f"project {name!r} has no {what} yet")
        with open(path, encoding="utf-8") as f:
            return f.read()

    @server.resource(
        "certo://projects/{name}/status",
        name="project_status",
        title="A project's status",
        description=(
            "The project's .certo/STATUS.md: the last run's task, verdict, checks and "
            "how to continue it."
        ),
        mime_type="text/markdown",
    )
    def project_status(name: str) -> str:
        from .project_state import status_path

        return _project_file(name, status_path, "STATUS.md")

    @server.resource(
        "certo://projects/{name}/runs",
        name="project_runs",
        title="A project's runs",
        description=(
            "The project's .certo/RUNS.md: every run in it, with its verdict, models, "
            "time and cost."
        ),
        mime_type="text/markdown",
    )
    def project_runs(name: str) -> str:
        from .run_history import runs_path

        return _project_file(name, runs_path, "RUNS.md")

    return server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo mcp",
        description=(
            "Run Certo as an MCP server over stdio, for an editor or an agent. The client "
            "starts this command; tools run tasks and checks in projects under "
            "CERTO_PROJECTS_DIR, or in folders inside a --root."
        ),
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "A folder the tools may work in, with every folder inside it, besides the "
            "projects under CERTO_PROJECTS_DIR. Repeat it for more than one."
        ),
    )
    return parser


def mcp_main(argv: list[str]) -> int:
    import sys

    args = _build_parser().parse_args(argv)
    for root in args.root:
        if not os.path.isdir(root):
            print(f"Error: --root {root} is not a folder", file=sys.stderr)
            return 1

    def load() -> Config:
        return load_config()

    try:
        # The model may come from a tool's argument or the model files, so
        # it isn't required to start.
        with defer_llm_check():
            cfg = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    folders = Folders(cfg.projects_dir, args.root)
    server = build_server(RunManager(load=load), folders, load=load)
    print(
        "Certo MCP server on stdio. Projects: "
        + folders.projects_dir
        + "".join(f"; root: {r}" for r in folders.roots),
        file=sys.stderr,
    )
    server.run("stdio")
    return 0
