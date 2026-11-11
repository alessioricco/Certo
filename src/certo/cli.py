"""CLI entry point: `python -m certo "<task>"` (also installed as `certo`)."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import shutil
import sys
import textwrap
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from . import __version__, update_check
from .acceptance import AcceptanceCheck, AcceptanceCheckError, parse_acceptance_checks
from .api import (
    NothingToDo,
    RunOptions,
    UsageError,
    load_run_ladder,
    plan_run,
    prepare_workspace,
    resolve_config,
    run_milestones,
)
from .banner import format_banner
from .config import (
    ConfigError,
    DEFAULT_PROJECTS_DIR,
    load_config,
    load_settings_files,
)
from .verification import _build_completion_contract, detect_project, run_full_verification
from .escalation import format_rung_lines
from .model_catalog import ModelCatalogEntry
from .milestones import (
    clear_state,
)
from .project_state import (
    status_path,
)
from .result import run_result, usage_dict
from .run_history import append_run, note_models_in_readme, run_entry
from .run_progress import RunProgress
from .run_report import report_relpath, write_report
from .worktree import was_created_by_certo, worktree_warning

if TYPE_CHECKING:
    from openhands.sdk.event import ActionEvent


# The SDK takes about 2 seconds to import, so the modules that load it
# (runner, init_cmd, skills) are imported only by the commands that use
# them: `certo --version`, `--help` and `certo verify` start at once. These
# wrappers keep the names on this module, where tests replace them.
def run_task(*args: Any, **kwargs: Any) -> Any:
    from .runner import run_task as _run_task

    return _run_task(*args, **kwargs)


def init_main(*args: Any, **kwargs: Any) -> int:
    from .init_cmd import init_main as _init_main

    return _init_main(*args, **kwargs)


def check_main(*args: Any, **kwargs: Any) -> int:
    from .init_cmd import check_main as _check_main

    return _check_main(*args, **kwargs)


def run_sample_task(*args: Any, **kwargs: Any) -> Any:
    from .init_cmd import run_sample_task as _run_sample_task

    return _run_sample_task(*args, **kwargs)


_URL_FETCH_TIMEOUT_SECONDS = 15


def _flag(name: str) -> str:
    """An option as the command line spells it, for `api`'s messages."""
    return "--" + name.replace("_", "-")


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _unproven_states() -> tuple[str, ...]:
    from .runner import UNPROVEN_STATES

    return UNPROVEN_STATES


def _confirm_pending_actions(pending: Sequence[ActionEvent]) -> bool:
    """Interactive terminal handler for `CERTO_CONFIRM_MODE=always`:
    prints each pending action and asks the user to approve or reject it.
    Any answer other than an explicit yes rejects — the safer default for
    a prompt nobody may be watching closely.
    """
    print("\n--- Confirmation required (CERTO_CONFIRM_MODE=always) ---")
    for action in pending:
        print(f"  {action.tool_name}: {action.action}")
    answer = input("Approve? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _prompt_for_continuation(narrative: str) -> str | None:
    """Interactive terminal handler for `CERTO_INTERACTIVE=yes`: prints
    the agent's latest reply and lets the user type a follow-up, or press
    Enter to accept it as done. The SDK can't tell a genuine clarifying
    question apart from real completion (see agent.py's `_AUTONOMOUS_SUFFIX`
    docstring), so this always offers the choice rather than guessing which
    one just happened.
    """
    if narrative:
        print(f"\n{narrative}\n")
    reply = input("Your reply (Enter to finish the task): ").strip()
    return reply or None


def _prompt_for_model_choice(
    candidates: list[ModelCatalogEntry], recommended_index: int, reason: str
) -> int:
    """Interactive terminal handler for `CERTO_MODEL_SELECTION=auto`: shows
    the full ranked candidate list and lets the user accept the recommended
    one (Enter) or type the number of an alternative instead.
    """
    print(f"\n{reason}")
    for i, entry in enumerate(candidates):
        ratings = ", ".join(f"{axis}={value}" for axis, value in entry.ratings.items())
        marker = " (recommended)" if i == recommended_index else ""
        print(f"  [{i}] {entry.name}{marker} — {ratings}")
        if entry.description:
            print(f"      {entry.description}")
    answer = input(
        f"Use recommended model [{candidates[recommended_index].name}]? [Y/n or a number]: "
    ).strip()
    if not answer or answer.lower() in ("y", "yes"):
        return recommended_index
    try:
        choice = int(answer)
    except ValueError:
        return recommended_index
    if 0 <= choice < len(candidates):
        return choice
    return recommended_index


def _confirm_escalation(question: str) -> bool:
    """Interactive terminal handler for an escalation climb: Enter or yes
    climbs, anything else stops with the current verdict."""
    try:
        answer = input(f"\n{question} [Y/n] ").strip().lower()
    except EOFError:
        return False
    return answer in ("", "y", "yes")


def _print_progress(line: str) -> None:
    print(line, flush=True)


def resolve_task_source(value: str) -> str:
    """Resolve the `task` argument to actual task text.

    Checked in order: an http(s) URL is fetched (the scheme check is also
    what keeps a bare `file://...` value from ever reaching urlopen); else an
    existing local file is read; else the value is used as literal task
    text, unchanged.
    """
    if _looks_like_url(value):
        try:
            with urllib.request.urlopen(value, timeout=_URL_FETCH_TIMEOUT_SECONDS) as resp:
                content = resp.read().decode("utf-8")
        except (urllib.error.URLError, UnicodeDecodeError) as exc:
            raise ValueError(f"Failed to fetch task from URL {value!r}: {exc}") from exc
    elif os.path.isfile(value):
        try:
            with open(value, encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            raise ValueError(f"Failed to read task file {value!r}: {exc}") from exc
    else:
        return value

    content = content.strip()
    if not content:
        raise ValueError(f"Task content from {value!r} is empty")
    return content


def resolve_acceptance_checks(value: str) -> list[AcceptanceCheck]:
    """Resolve the `--acceptance-checks` argument to parsed `AcceptanceCheck`
    objects — a JSON array of check definitions, either read from an
    existing local file or given inline (same "existing file wins over
    literal text" pattern as `resolve_task_source`, minus the URL-fetch
    case: an acceptance-check *list* has no legitimate reason to come from
    a remote URL the way a task description might).
    """
    if os.path.isfile(value):
        try:
            with open(value, encoding="utf-8") as f:
                raw = f.read()
        except OSError as exc:
            raise ValueError(f"Failed to read acceptance checks file {value!r}: {exc}") from exc
    else:
        raw = value

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--acceptance-checks must be valid JSON: {exc}") from exc
    if not isinstance(data, list):
        # ValueError, not TypeError (ruff's TRY004 suggestion): every error
        # this function raises must be a ValueError so main()'s single
        # `except ValueError` catches all of them uniformly.
        raise ValueError(  # noqa: TRY004
            "--acceptance-checks must be a JSON array of check objects."
        )

    try:
        return parse_acceptance_checks(data)
    except AcceptanceCheckError as exc:
        raise ValueError(str(exc)) from exc


# The subcommands `_main` dispatches before argparse runs, listed in `certo
# --help` the way argparse lists options.
_COMMANDS: tuple[tuple[str, str], ...] = (
    ("init [FOLDER]", "Create a ready-to-use workspace: settings, a model and sample tasks."),
    ("check", "Test that the configured model works, with one small real call."),
    ("verify [PATH]", "Run Certo's checks on a project, without an agent or a model."),
    ("bench", "Compare models and strategies on tasks graded by hidden tests."),
    ("checkpoints [PATH]", "List the snapshots Certo took of a project during its runs."),
    ("rollback N [PATH]", "Put a project's files back as they were at checkpoint N."),
    ("skills", "See, add and remove the skills a run gets."),
    ("models", "Manage your list of models (models_list.yaml)."),
    ("mcp", "Run Certo as an MCP server, for an editor or an agent."),
)


def _commands_help(width: int | None = None) -> str:
    """The "commands:" section of `certo --help`, laid out as argparse lays
    out options: names indented 2, help from column 24, wrapped to the
    terminal's width."""
    if width is None:
        width = shutil.get_terminal_size().columns - 2
    help_col = 24
    lines = ["commands:"]
    for name, text in _COMMANDS:
        wrapped = textwrap.wrap(text, max(width - help_col, 20))
        head = f"  {name}"
        if len(head) + 2 > help_col:
            lines.append(head)
        else:
            lines.append(head.ljust(help_col) + wrapped.pop(0))
        lines.extend(" " * help_col + line for line in wrapped)
    lines.append("")
    lines.append("Each command takes --help.")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo",
        description="Run a coding task through Certo.",
        epilog=_commands_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help=(
            "The task to give the agent — literal text, a path to a local "
            "file containing it, or an http(s) URL to fetch it from. With "
            "--resume it is optional, and is sent as an extra instruction."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Continue the last run in this folder (or --project) from where it "
            "stopped, using the state Certo keeps in .certo/. The agent gets "
            "its earlier conversation back when it is saved, and Certo's "
            "record of the last verdict and failing checks."
        ),
    )
    milestones = parser.add_mutually_exclusive_group()
    milestones.add_argument(
        "--milestones",
        action="store_true",
        help=(
            "Run the task file milestone by milestone: each '## Milestone N: title' "
            "heading starts one, run in its own conversation and verified before "
            "the next starts. A milestone may hold an ```acceptance block, the same "
            "JSON as --acceptance-checks. --resume continues the first milestone "
            "not verified. A task file with two or more such headings, numbered "
            "1, 2, 3..., runs this way without the flag."
        ),
    )
    parser.add_argument(
        "--from-milestone",
        type=int,
        default=None,
        metavar="N",
        help=(
            "With a task file in milestones: start at milestone N (as Certo numbers "
            "them, 'Milestone N of M'), skipping those before it. Without it, a task "
            "file run again in the same project goes on from the first milestone "
            "not verified; --from-milestone 1 starts again from the first."
        ),
    )
    milestones.add_argument(
        "--no-milestones",
        action="store_true",
        help=(
            "Send a task file written in milestones as one task, as it is, instead "
            "of running it milestone by milestone."
        ),
    )
    parser.add_argument(
        "--execution",
        choices=("local", "docker"),
        default=None,
        help=("Override CERTO_EXECUTION for this run. Defaults to the value in .env (or 'local')."),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Override CERTO_MAX_ITERATIONS for this run: the most steps the agent "
            "may take. In milestone mode each milestone gets N steps."
        ),
    )
    parser.add_argument(
        "--max-time",
        type=int,
        default=None,
        metavar="MINUTES",
        help=(
            "Override CERTO_MAX_TASK_SECONDS for this run, in minutes: the time "
            "budget. In milestone mode each milestone gets MINUTES."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Override CERTO_LLM_MODEL for this run only, without touching .env — "
            "e.g. to compare how two models handle the same task."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override CERTO_LLM_API_KEY for this run only (pairs with --model when swapping providers).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override CERTO_LLM_BASE_URL for this run only (e.g. to point at a local model endpoint).",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help=(
            "Override CERTO_LLM_REASONING_EFFORT for this run only, without touching "
            ".env — e.g. to compare how the same model behaves at different "
            "effort levels. Common values: none | minimal | low | medium | "
            "high | xhigh | max (provider-neutral; none or off disables "
            "reasoning; leave unset for the default)."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Project name. The agent's workspace becomes "
            "<CERTO_PROJECTS_DIR>/<project> (created if missing), so each "
            "project's generated software lands in its own subfolder. "
            "Defaults to CERTO_WORKSPACE when omitted."
        ),
    )
    parser.add_argument(
        "--agents-md",
        default=None,
        help=(
            "Content to write as this project's AGENTS.md before running the "
            "task — persistent, project-specific facts/conventions the agent "
            "picks up on this and every future task against the same "
            "project. Requires --project (there's no project directory to "
            "write into otherwise)."
        ),
    )
    parser.add_argument(
        "--independent-tests",
        action="store_true",
        help=(
            "Before the build, have a separate conversation write tests from "
            "the task and the project as it is then; after the verdict, run "
            "them and report the result. Report only: the verdict doesn't "
            "change. Local runs only. The same as CERTO_INDEPENDENT_TESTS=yes."
        ),
    )
    parser.add_argument(
        "--independent-tests-strict",
        action="store_true",
        help=(
            "Like --independent-tests, but a 'verified' run whose independent "
            "tests failed ends 'independent_failed' (exit 1). The same as "
            "CERTO_INDEPENDENT_TESTS_STRICT=yes."
        ),
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "Allow the agent to pause and ask you a question instead of "
            "always pushing forward autonomously. When the initial run "
            "reaches a normal stop, you'll be prompted at the terminal to "
            "reply (continuing the task) or press Enter to accept it as "
            "done. Only the initial run is interactive — the automated "
            "task_tracker-completion and test-verification retry loops "
            "that follow still run fully autonomously, same as today. Off "
            "by default (current fully-autonomous behavior unchanged)."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Print the full output of the agent: the whole system prompt, the "
            "task with the skills Certo adds, and the SDK's own logs. By default "
            "each of these is one line. The same as CERTO_VERBOSE=yes."
        ),
    )
    parser.add_argument(
        "--auto-model",
        action="store_true",
        help=(
            "Pick the best-fit model for this task from a hand-curated "
            "catalog (models.yaml, or CERTO_MODELS_FILE), scored by task "
            "type instead of always using CERTO_LLM_MODEL. Falls back to the next "
            "candidate on a provider-level failure (auth/rate-limit/outage) "
            "or a failed verification/task_tracker retry. Combine with "
            "--interactive to be prompted before each choice instead of it "
            "deciding automatically. Off by default (current single-model "
            "behavior unchanged)."
        ),
    )
    parser.add_argument(
        "--escalate",
        nargs="?",
        const="",
        default=None,
        metavar="LADDER",
        help=(
            "Start on the first model of a ladder from escalation.yaml and move to the "
            "next one only when Certo's verification shows the model couldn't finish, or "
            "its provider fails. LADDER names a ladder under escalation.ladders; without "
            "it, the ladder named 'default' is used, else one built from the ratings. "
            'With only one value after it (certo --escalate "task"), that value is the '
            "task. Can't be combined with --auto-model or --model."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print the run's result as JSON on standard output, and everything else "
            "on standard error: the verdict, the checks, the cost and more, in the "
            "format described in docs/reference/json-result.md."
        ),
    )
    parser.add_argument(
        "--require-verification",
        action="store_true",
        help=(
            "Treat an 'inconclusive' verification result (nothing runnable "
            "confirmed the software works — e.g. an unknown project type, a "
            "missing tool, or a project with no tests yet) or an 'unchanged' "
            "one (the agent changed no file) as a failure: nonzero exit, same "
            "as retry_exhausted/timed_out/stuck/etc. Off by default — both "
            "exit 0, since nothing was proven broken, only unproven."
        ),
    )
    parser.add_argument(
        "--acceptance-checks",
        default=None,
        help=(
            "Optional, opt-in machine-checkable acceptance criteria: a JSON "
            "array of check objects, either given inline or as a path to a "
            "local JSON file. Each object is "
            '{"kind": "file_exists"|"file_contains", "path": "relative/path", '
            '"contains": "text" (file_contains only), "required": true '
            '(default), "description": "..."}. `path` is always resolved '
            "relative to the task's own workspace and cannot escape it "
            "(absolute paths and '..' are rejected). A failing required "
            "check downgrades an otherwise-'verified' result to "
            "'acceptance_failed'; a failing optional check is recorded but "
            "never blocks 'verified'."
        ),
    )
    return parser


# Final verdicts that exit nonzero, for an agent run and for `certo verify`
# alike. "failed" can only be final for `certo verify`, which never retries.
_FAILING_STATES = (
    "failed",
    "retry_exhausted",
    "no_progress",
    "timed_out",
    "incomplete",
    "confirmation_required",
    "budget_exhausted",
    "cost_exhausted",
    "acceptance_failed",
    "independent_failed",
    "stuck",
)


def _build_verify_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo verify",
        description=(
            "Run Certo's verification on a project without an agent or an LLM: "
            "project detection, the project's own environment, then every check "
            "Certo runs after an agent finishes. No CERTO_LLM_MODEL needed."
        ),
    )
    parser.add_argument(
        "path", nargs="?", default=".", help="Project directory (default: current directory)."
    )
    parser.add_argument(
        "--require-verification",
        action="store_true",
        help="Exit nonzero for 'inconclusive' too, not only for a failure.",
    )
    return parser


def verify_main(argv: list[str]) -> int:
    """`certo verify [PATH]`: the post-agent verification on its own.

    Same pipeline as runner.py's post-hoc check (`run_full_verification`),
    run locally against PATH once, with no retries (there's no agent to send
    a failure back to), so a failure is final here.
    """
    args = _build_verify_parser().parse_args(argv)
    path = os.path.abspath(args.path)
    if not os.path.isdir(path):
        print(f"Error: {args.path} is not a directory", file=sys.stderr)
        return 1

    detection = detect_project(path)
    print(f"Project: {path} ({detection.language})")
    run = run_full_verification(path)
    for notice in run.notices:
        print(f"Certo: {notice}")
    for check in run.checks:
        print(
            f"  {check.status:<11} {check.name}" + (f"  ({check.command})" if check.command else "")
        )
    for check in run.failing + run.timed_out_checks:
        if check.output.strip():
            print(f"\n--- {check.name} output ---\n{check.output.rstrip()}")

    state = run.state
    print(f"\nVerification: {state}")
    contract = _build_completion_contract("certo verify", run, skipped=False, aborted=False)
    for note in contract.limitations:
        print(f"  - {note}")
    if state in _FAILING_STATES:
        return 1
    if args.require_verification and state == "inconclusive":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    check = None if argv[:1] == ["bench"] else _start_update_check()
    try:
        return _main(argv)
    finally:
        line = check.notice() if check is not None else None
        if line:
            print(f"\n{line}", file=sys.stderr)


def _start_update_check() -> update_check.UpdateCheck | None:
    """A check for a newer Certo on PyPI, or None (update_check.py). The
    settings files are read into a copy of the environment, so
    CERTO_UPDATE_CHECK=0 in a `.env` works before the command loads it."""
    try:
        environ = dict(os.environ)
        load_settings_files(environ=environ)
        return update_check.start(environ)
    except Exception:  # noqa: BLE001 - never let the check stop a command
        return None


def _main(argv: list[str]) -> int:
    # `verify`, `init`, `check`, `models`, `skills`, `bench`, `checkpoints`,
    # `mcp` and `rollback` are
    # subcommands only as the exact, whole first argument. A task is always
    # one argument (quoted), so "verify the login flow" or "init a repo" can
    # never match, and `certo -- verify` still runs the one-word task.
    if argv and argv[0] == "verify":
        return verify_main(argv[1:])
    if argv and argv[0] == "init":
        return init_main(argv[1:], run_sample=run_sample_task)
    if argv and argv[0] == "check":
        return check_main(argv[1:])
    if argv and argv[0] == "models":
        from .models_cmd import models_main

        return models_main(argv[1:])
    if argv and argv[0] == "skills":
        from .skills_cmd import skills_main

        return skills_main(argv[1:])
    if argv and argv[0] == "bench":
        from .bench import bench_main

        return bench_main(argv[1:])
    if argv and argv[0] == "checkpoints":
        from .checkpoints_cmd import checkpoints_main

        return checkpoints_main(argv[1:])
    if argv and argv[0] == "mcp":
        from .mcp_server import mcp_main

        return mcp_main(argv[1:])
    if argv and argv[0] == "rollback":
        from .checkpoints_cmd import rollback_main

        return rollback_main(argv[1:])
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.json:
        return _run_task_command(args, parser, None)
    # stdout carries only the JSON result: everything a run prints goes to
    # stderr instead (docs/reference/json-result.md).
    out = sys.stdout
    holder: dict[str, Any] = {}
    with contextlib.redirect_stdout(sys.stderr):
        code = _run_task_command(args, parser, holder)
    if "result" in holder:
        out.write(json.dumps(holder["result"], indent=2) + "\n")
        out.flush()
    return code


def _written_in_milestones(args: argparse.Namespace, task: str | None) -> int:
    """How many milestones the task file is written in, when the run should
    switch to milestones by itself: a file (not text or a URL), a new run,
    neither --milestones nor --no-milestones given. 0 otherwise."""
    from .milestones import written_in_milestones

    if task is None or args.milestones or args.no_milestones or args.resume:
        return 0
    if not os.path.isfile(args.task):
        return 0
    return written_in_milestones(task)


def _project_from_task(args: argparse.Namespace, task: str | None, cfg: Any) -> str | None:
    """The project name Certo picks for a new task run from a Certo
    workspace without --project, after printing it; None when Certo keeps
    the folder it runs in (a project given, a resume, CERTO_WORKSPACE set
    elsewhere, or a folder that is itself a project)."""
    from .project_root import is_certo_workspace, project_name_for_task, unused_project_name

    if args.project is not None or args.resume or task is None:
        return None
    if os.path.abspath(cfg.workspace) != os.getcwd():
        return None
    if not is_certo_workspace(cfg.workspace, cfg.projects_dir):
        return None
    wanted = project_name_for_task(args.task, task)
    name = unused_project_name(cfg.projects_dir, wanted)
    where = os.path.normpath(os.path.join(cfg.projects_dir, name))
    print(f"Project: {where}, named after the task. The agent works only in that folder.")
    if name != wanted:
        print(
            f"  {os.path.normpath(os.path.join(cfg.projects_dir, wanted))} already exists; "
            f"--project {wanted} works on it instead."
        )
    return name


def _run_task_command(
    args: argparse.Namespace, parser: argparse.ArgumentParser, holder: dict[str, Any] | None
) -> int:
    """`certo "task"` after its flags are parsed. With `holder`, the run's JSON
    result is put in `holder["result"]` once the run has started."""
    if args.task is None and args.escalate and not args.resume:
        # `certo --escalate "task"`: LADDER is optional, so argparse took the
        # task for a ladder name. A ladder with no task can't run, so it was
        # the task, on the default ladder. (`certo --escalate hard "task"`
        # still names the ladder.)
        args.task, args.escalate = args.escalate, ""
    if args.task is None and not args.resume:
        parser.error("the following arguments are required: task")

    task = None
    if args.task is not None:
        try:
            task = resolve_task_source(args.task)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    # A task file written in milestones runs in milestones (DECISIONS.md).
    auto_milestones = _written_in_milestones(args, task)
    if auto_milestones:
        args.milestones = True
        print(
            f"Certo: {args.task} is written in {auto_milestones} milestones, so it runs "
            "milestone by milestone (--no-milestones runs it as one task)."
        )

    options = RunOptions(
        project=args.project,
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        reasoning_effort=args.reasoning_effort,
        escalate=args.escalate,
        auto_model=args.auto_model,
        execution=args.execution,
        interactive=args.interactive,
        independent_tests=True if args.independent_tests else None,
        independent_tests_strict=args.independent_tests_strict,
        verbose=args.verbose,
        agents_md=args.agents_md,
        max_steps=args.max_steps,
        max_minutes=args.max_time,
    )
    try:
        cfg = resolve_config(options, load=lambda: load_config(), spell=_flag)
    except UsageError as exc:
        print(f"Error: {exc}.", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    # In a Certo workspace, a new task gets its own project folder, named
    # after the task: the agent's root (project_root.py).
    named = _project_from_task(args, task, cfg)
    if named is not None:
        args.project = named
        options = replace(options, project=named)
        try:
            cfg = resolve_config(options, load=lambda: load_config(), spell=_flag)
        except (UsageError, ConfigError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    try:
        plan = plan_run(
            cfg,
            task=task,
            resume=args.resume,
            milestones_file=args.task if args.milestones and not args.resume else None,
            from_project=args.project is not None,
            want_milestones=args.milestones,
            from_milestone=args.from_milestone,
            spell=_flag,
        )
    except NothingToDo as exc:
        print(exc)
        return 0
    except UsageError as exc:
        hint = (
            " It has milestone headings, so Certo read it as milestones; "
            "--no-milestones sends it as one task."
            if auto_milestones
            else ""
        )
        print(f"Error: {exc}{hint}", file=sys.stderr)
        return 1
    resume_from = plan.resume_from
    milestone_state = plan.milestones
    milestone_restart = plan.restart

    # After the plan is known: a resume of milestones counts too.

    try:
        ladder = load_run_ladder(
            cfg, on_warning=lambda w: print(f"Warning (models.yaml): {w}", file=sys.stderr)
        )
    except ValueError as exc:  # EscalationError, ModelCatalogError
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    acceptance_checks: list[AcceptanceCheck] | None = None
    if args.acceptance_checks is not None:
        try:
            acceptance_checks = resolve_acceptance_checks(args.acceptance_checks)
        except ValueError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1

    # OpenHands plugins from outside the project would load with no way to
    # turn them off (plugins.py): refused before anything is created.
    try:
        prepare_workspace(cfg, options)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # After every check that can refuse the run, so it only shows for a run
    # that starts.
    for line in format_banner(cfg, ladder=ladder, project=args.project):
        print(line)
    if milestone_state is not None:
        count = len(milestone_state.plan)
        print(f"Milestones: {count}, each verified before the next starts")
        if plan.note:
            print(plan.note)
    elif resume_from is not None:
        print(f"Resuming: {_first_line(resume_from.task)}")
    # A third-party skill replacing an official one is said before the run
    # (skill_library.py).
    from .skill_library import collect

    for line in collect(cfg, cfg.workspace, own=False).notices:
        print(line)

    certo_made = args.project is not None and was_created_by_certo(cfg.projects_dir, args.project)
    if not cfg.no_worktree_warning and not certo_made:
        warning = worktree_warning(cfg.workspace)
        if warning:
            print(warning, file=sys.stderr)

    on_confirm = _confirm_pending_actions if cfg.confirm_mode == "always" else None
    on_awaiting_input = _prompt_for_continuation if cfg.interactive else None
    on_model_choice = (
        _prompt_for_model_choice if (cfg.model_selection == "auto" and cfg.interactive) else None
    )
    save_state = cfg.save_state or resume_from is not None or milestone_state is not None
    resume_hint = "certo --resume" + (f" --project {args.project}" if args.project else "")
    if cfg.projects_dir != DEFAULT_PROJECTS_DIR:
        resume_hint = f"CERTO_PROJECTS_DIR={shlex.quote(cfg.projects_dir)} {resume_hint}"
    started_at = datetime.now(UTC)
    history = {"task": resume_from.task if resume_from is not None else (task or "")}
    report: dict[str, str] = {}

    def record_run(ended: str, outcome=None, summary=None) -> None:
        if not save_state:
            return
        entry = run_entry(cfg, ladder, history["task"], ended, started_at, outcome, summary)
        entry = replace(entry, resumed=resume_from is not None, report=report_relpath(started_at))
        try:
            append_run(cfg.workspace, entry)
        except OSError as exc:
            print(f"Warning: couldn't add this run to .certo/RUNS.md ({exc}).", file=sys.stderr)

    # The progress line (run_progress.py): one for the whole run, so its
    # time and cost count every milestone.
    progress = (
        RunProgress(say=_print_progress, every_seconds=cfg.progress_seconds)
        if cfg.progress_seconds > 0
        else None
    )

    def run_one(text: str, resume, instruction: str | None, checks):
        if progress is not None and milestone_state is not None:
            total = len(milestone_state.plan.milestones)
            progress.where = f"milestone {milestone_state.current} of {total}"
            progress.checks = ""
        result = run_task(
            text,
            cfg=cfg,
            on_confirm=on_confirm,
            acceptance_checks=checks,
            on_awaiting_input=on_awaiting_input,
            on_model_choice=on_model_choice,
            project=args.project,
            save_state=save_state,
            resume_from=resume,
            resume_instruction=instruction,
            ladder=ladder,
            on_escalate=_confirm_escalation if cfg.interactive else None,
            on_notice=_print_progress,
            run_progress=progress,
        )
        summary = result.outcome.run_summary
        if progress is not None and summary is not None:
            progress.cost_before += summary.total_cost
        return result

    if save_state and milestone_state is None and resume_from is None:
        clear_state(cfg.workspace)  # a new task here isn't the old milestones

    def keep_result(outcome, error: str | None = None) -> None:
        # The JSON result for --json, and the run's report (run_report.py).
        if holder is None and not save_state:
            return
        milestones = None
        if milestone_state is not None:
            milestones = [
                {
                    "number": m.number,
                    "title": m.title,
                    "verdict": milestone_state.verdicts.get(m.number),
                    "skills": (
                        list(milestone_state.skills[m.number])
                        if m.number in milestone_state.skills
                        else None
                    ),
                    "usage": usage_dict(milestone_state.usage.get(m.number)),
                }
                for m in milestone_state.plan.milestones
            ]
        result = run_result(
            outcome,
            task=history["task"],
            workspace=os.path.abspath(cfg.workspace),
            project=args.project,
            milestones=milestones,
            error=error,
        )
        if holder is not None:
            holder["result"] = result
        if save_state:
            try:
                report["path"] = write_report(cfg.workspace, result, started_at)
            except OSError as exc:
                print(f"Warning: couldn't write the run report ({exc}).", file=sys.stderr)

    try:
        if milestone_state is None:
            messages = run_one(
                resume_from.task if resume_from is not None else task,
                resume_from,
                task if resume_from is not None else None,
                acceptance_checks,
            )
            outcome = messages.outcome
        else:
            outcome = run_milestones(
                milestone_state,
                cfg,
                run_one,
                say=lambda line: print(line, flush=True),
                resume_from=resume_from,
                restart=milestone_restart,
                instruction=task if args.resume else None,
                acceptance_checks=acceptance_checks,
                history=history,
                record_run=record_run,
            )
    except KeyboardInterrupt as exc:
        # The runner attaches the usage up to the interrupt to the exception.
        record_run("interrupted", summary=getattr(exc, "run_summary", None))
        keep_result(None, "interrupted")
        print("\nInterrupted.", file=sys.stderr)
        if save_state:
            print(f"Continue with: {resume_hint}", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean CLI error, not a traceback
        record_run(
            f"error: {_first_line(str(exc) or type(exc).__name__)}",
            summary=getattr(exc, "run_summary", None),
        )
        keep_result(None, str(exc) or type(exc).__name__)
        print(f"Error: {exc}", file=sys.stderr)
        if save_state:
            print(f"Continue with: {resume_hint}", file=sys.stderr)
        return 1

    # The agent's last message is already on screen (the SDK's visualizer
    # printed it) and Certo's notices were printed as they happened, so
    # nothing is printed again here.

    # Make the terminal outcome explicit rather than letting the agent's own
    # (possibly optimistic) last message stand as the only signal — see
    # runner.py's TaskOutcome / MANUAL.md "Test verification". A task whose
    # verification failed and couldn't be fixed, made no observable progress
    # on a fix attempt, kept timing out, whose own task_tracker list was
    # left incomplete, needed a confirm-mode approval nobody could answer,
    # ran out of its shared CERTO_MAX_TASK_SECONDS budget, failed a
    # required --acceptance-checks criterion, or whose run never reached a
    # coherent finish, is a nonzero exit; "inconclusive" (nothing runnable
    # to check) is not an error but is still printed so it isn't mistaken
    # for a confirmed pass — unless --require-verification opted into
    # treating "nothing was checked" as a failure too (off by default: this
    # is a real behavior change a caller must ask for, not a silent default
    # flip — see DECISIONS.md).
    if milestone_state is None:
        record_run(outcome.verification_state, outcome)
    keep_result(outcome)
    # Only in a project folder Certo created: it never edits the README of
    # a project you brought.
    if certo_made:
        try:
            note_models_in_readme(cfg.workspace, _models_that_ran(cfg, outcome))
        except OSError as exc:
            print(f"Warning: couldn't add the model note to README.md ({exc}).", file=sys.stderr)
    if outcome.model_decisions:
        final = outcome.model_decisions[-1]
        print(f"\nModel used: {final.chosen} (see MODEL_DECISIONS.md for the full history)")
    print(f"\nVerification: {outcome.verification_state}")
    for note in outcome.completion_contract.limitations:
        print(f"  - {note}")
    if outcome.independent_tests is not None:
        from .independent_tests import failing_tests, report_line, set_lines

        print(report_line(outcome.independent_tests, strict=cfg.independent_tests_strict))
        details = set_lines(outcome.independent_tests) or failing_tests(outcome.independent_tests)
        for line in details:
            print(f"  - {line}")
    if outcome.run_summary is not None:
        print("\nRun summary:")
        for line in outcome.run_summary.format_lines():
            print(f"  {line}")
    # In milestone mode each milestone's rungs were printed under its verdict.
    if outcome.rungs and milestone_state is None:
        for line in format_rung_lines(outcome.rungs, outcome.final_rung):
            print(f"  {line}")
    if report.get("path"):
        print(f"\nReport: {_short_path(report['path'])}")
    failing = outcome.verification_state in _FAILING_STATES or (
        args.require_verification and outcome.verification_state in _unproven_states()
    )
    if failing and save_state:
        status = _short_path(status_path(cfg.workspace))
        print(f"\nWhere it stopped: {status}. Continue with: {resume_hint}")
    if save_state and cfg.checkpoints:
        hint = _checkpoints_hint(cfg.workspace)
        if hint:
            print(hint)
    return 1 if failing else 0


def _short_path(path: str) -> str:
    """`path` relative to the current folder, or absolute when that is
    shorter (a project far away would be a long `../..` chain)."""
    path = os.path.abspath(path)
    try:
        return min(path, os.path.relpath(path), key=len)
    except ValueError:
        return path  # Windows: no relative path between different drives


def _checkpoints_hint(workspace: str) -> str | None:
    """One line naming the project's checkpoints (checkpoints.py)."""
    from .checkpoints import git_available, list_checkpoints

    try:
        count = len(list_checkpoints(workspace)) if git_available() else 0
    except Exception:  # noqa: BLE001 - a hint, never the run's outcome
        return None
    if not count:
        return None
    where = _short_path(workspace)
    path = "" if where == "." else f" {shlex.quote(where)}"
    return (
        f"Checkpoints: {count} (list them: certo checkpoints{path}; "
        f"go back to one: certo rollback N{path})"
    )


def _models_that_ran(cfg, outcome) -> list[str]:
    if outcome.rungs:
        return [r.model for r in outcome.rungs if r.wrote_code]
    summary = outcome.run_summary
    if summary and summary.models:
        return [m.model for m in summary.models]
    return [cfg.model] if cfg.model else []


def _first_line(text: str, limit: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
