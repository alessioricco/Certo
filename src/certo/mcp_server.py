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

INSTRUCTIONS = (
    "Certo runs a coding task with an agent, then checks the result itself: it runs the "
    "project's tests and checks and gives a verdict (verified, or why not). Start a task "
    "with run_task, follow it with run_status and run_events, and stop it with run_cancel. "
    "verify checks a folder without an agent. Work happens only in a named project "
    "(project) or in a folder the server was started with (folder)."
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
    ) -> dict[str, Any]:
        """Start a coding task: an agent works in the project, then Certo runs the
        project's checks and gives a verdict. Returns at once with a run_id; follow it
        with run_status and run_events. `project` is a project name (created if new)
        under Certo's projects folder; `folder` is the full path of a folder inside one
        the server allows. `model` overrides the configured model; `escalate` climbs a
        ladder of models ("" for the default ladder). `acceptance_checks` are extra file
        checks, as in `certo --acceptance-checks`. The agent can change any file in the
        folder and run commands there."""
        from .acceptance import parse_acceptance_checks

        options = RunOptions(model=model, escalate=escalate, **folders.options(project, folder))
        checks = parse_acceptance_checks(acceptance_checks) if acceptance_checks else None
        run = manager.start(task, options, acceptance_checks=checks)
        return {
            "run_id": run.id,
            "state": run.state,
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
        project's own environment (.venv) to run them. Returns the verdict and each
        check."""
        from .result import check_dict
        from .verification import _build_completion_contract, run_full_verification

        cfg = resolve_config(RunOptions(**folders.options(project, folder)), load=load)
        path = os.path.abspath(cfg.workspace)
        if not os.path.isdir(path):
            raise UsageError(f"{path} doesn't exist")
        run = (verify_fn or run_full_verification)(path)
        contract = _build_completion_contract("certo verify", run, skipped=False, aborted=False)
        return {
            "workspace": path,
            "verdict": run.state,
            "checks": [check_dict(c) for c in run.checks],
            "notices": list(run.notices),
            "limitations": list(contract.limitations),
        }

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
