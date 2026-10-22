"""CLI entry point: `python -m certo "<task>"` (also installed as `certo`)."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from . import __version__
from .acceptance import AcceptanceCheck, AcceptanceCheckError, parse_acceptance_checks
from .banner import format_banner
from .catalog_check import load_checked_catalog
from .config import (
    ConfigError,
    DEFAULT_PROJECTS_DIR,
    defer_llm_check,
    ensure_llm_configured,
    load_config,
    override_llm,
    resolve_project_dir,
)
from .verification import _build_completion_contract, detect_project, run_full_verification
from .escalation import format_rung_lines, load_ladder
from .model_catalog import ModelCatalogEntry
from .project_state import load_record, status_path
from .run_history import RunEntry, append_run, note_models_in_readme
from .run_summary import model_label
from .worktree import record_created_project, was_created_by_certo, worktree_warning

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo",
        description="Run a coding task through Certo.",
        epilog=(
            "Other commands: certo init [FOLDER] creates a ready-to-use workspace; "
            "certo check tests that the configured model works; certo verify [PATH] "
            "checks a project without running an agent; certo bench compares models on "
            "tasks with hidden tests. Each takes --help."
        ),
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
    parser.add_argument(
        "--execution",
        choices=("local", "docker"),
        default=None,
        help=("Override CERTO_EXECUTION for this run. Defaults to the value in .env (or 'local')."),
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
    "acceptance_failed",
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
    # `verify`, `init`, `check`, `models`, `skills` and `bench` are
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
    parser = _build_parser()
    args = parser.parse_args(argv)
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

    try:
        has_llm_override = (
            args.model is not None
            or args.api_key is not None
            or args.base_url is not None
            or args.reasoning_effort is not None
        )
        # Apply --model/--api-key/--base-url/--reasoning-effort before the
        # required-field checks, so the flags alone can satisfy them (issue #11).
        if has_llm_override:
            with defer_llm_check():
                cfg = load_config()
            cfg = ensure_llm_configured(
                override_llm(
                    cfg,
                    model=args.model,
                    api_key=args.api_key,
                    base_url=args.base_url,
                    reasoning_effort=args.reasoning_effort,
                )
            )
        else:
            cfg = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.execution is not None:
        cfg = replace(cfg, execution=args.execution)

    if args.interactive:
        cfg = replace(cfg, interactive=True)

    if args.verbose:
        cfg = replace(cfg, verbose=True)

    if args.escalate is not None:
        if args.auto_model or args.model is not None:
            print(
                "Error: --escalate can't be combined with --auto-model or --model: the "
                "ladder decides which models run.",
                file=sys.stderr,
            )
            return 1
        cfg = replace(cfg, model_selection="escalate", escalation_ladder=args.escalate)
    elif args.auto_model:
        cfg = replace(cfg, model_selection="auto")
    elif cfg.model_selection == "escalate" and args.model is not None:
        print(
            "Error: --model can't be used while CERTO_MODEL_SELECTION=escalate: the "
            "ladder decides which models run.",
            file=sys.stderr,
        )
        return 1
    if cfg.model_selection == "escalate" and args.resume:
        print(
            "Error: --resume can't be combined with escalation. Resume continues one "
            "model's conversation; run it without --escalate.",
            file=sys.stderr,
        )
        return 1

    if args.agents_md is not None and args.project is None:
        print("Error: --agents-md requires --project", file=sys.stderr)
        return 1

    if args.project is not None:
        try:
            project_dir = resolve_project_dir(cfg.projects_dir, args.project)
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1
        if args.resume and not os.path.isdir(project_dir):
            print(f"Error: nothing to resume: {project_dir} doesn't exist.", file=sys.stderr)
            return 1
        cfg = replace(cfg, workspace=project_dir)

    resume_from = None
    if args.resume:
        resume_from = load_record(cfg.workspace)
        if resume_from is None:
            print(
                f"Error: nothing to resume in {os.path.abspath(cfg.workspace)}: Certo keeps "
                "the last run's state in .certo/, and there is none here (or it can't "
                "be read). Run a task first.",
                file=sys.stderr,
            )
            return 1
        if resume_from.verdict == "verified" and task is None:
            print(
                "The last run here already ended with 'verified'. To continue anyway, "
                'say what to do next: certo --resume "..."'
            )
            return 0

    ladder = None
    if cfg.model_selection == "escalate":
        try:
            ladder = load_ladder(
                cfg.models_file,
                cfg.models_list_file,
                cfg.escalation_ladder or None,
                escalation_file=cfg.escalation_file,
                task_profiles_file=cfg.task_profiles_file,
                on_warning=lambda w: print(f"Warning (models.yaml): {w}", file=sys.stderr),
            )
        except ValueError as exc:  # EscalationError, ModelCatalogError
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1
    elif cfg.model_selection == "auto":
        # Same timing as --escalate: refuse before the banner or any run
        # record. run_task() loads the catalog again to pick a model.
        try:
            load_checked_catalog(
                cfg.models_file,
                cfg.models_list_file,
                task_profiles_file=cfg.task_profiles_file,
                escalation_file=cfg.escalation_file,
                mode="auto",
            )
        except ValueError as exc:  # ModelCatalogError
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1

    acceptance_checks: list[AcceptanceCheck] | None = None
    if args.acceptance_checks is not None:
        try:
            acceptance_checks = resolve_acceptance_checks(args.acceptance_checks)
        except ValueError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1

    if args.project is not None:
        created = not os.path.exists(cfg.workspace)
        os.makedirs(cfg.workspace, exist_ok=True)
        if created:
            record_created_project(cfg.projects_dir, args.project)

    # After every check that can refuse the run, so it only shows for a run
    # that starts.
    for line in format_banner(cfg, ladder=ladder, project=args.project):
        print(line)
    if resume_from is not None:
        print(f"Resuming: {_first_line(resume_from.task)}")
    # A third-party skill replacing an official one, and the old skill
    # folders still in use, are said before the run (skill_library.py).
    from .skill_library import collect

    for line in collect(cfg, cfg.workspace, own=False).notices:
        print(line)

    certo_made = args.project is not None and was_created_by_certo(cfg.projects_dir, args.project)
    if not cfg.no_worktree_warning and not certo_made:
        warning = worktree_warning(cfg.workspace)
        if warning:
            print(warning, file=sys.stderr)

    if args.agents_md is not None:
        from .skills import write_project_context

        write_project_context(cfg.workspace, args.agents_md)

    on_confirm = _confirm_pending_actions if cfg.confirm_mode == "always" else None
    on_awaiting_input = _prompt_for_continuation if cfg.interactive else None
    on_model_choice = (
        _prompt_for_model_choice if (cfg.model_selection == "auto" and cfg.interactive) else None
    )
    save_state = cfg.save_state or resume_from is not None
    resume_hint = "certo --resume" + (f" --project {args.project}" if args.project else "")
    if cfg.projects_dir != DEFAULT_PROJECTS_DIR:
        resume_hint = f"CERTO_PROJECTS_DIR={shlex.quote(cfg.projects_dir)} {resume_hint}"
    started_at = datetime.now(UTC)
    history_task = resume_from.task if resume_from is not None else (task or "")

    def record_run(ended: str, outcome=None) -> None:
        if not save_state:
            return
        entry = _run_entry(cfg, ladder, history_task, ended, started_at, outcome)
        entry = replace(entry, resumed=resume_from is not None)
        try:
            append_run(cfg.workspace, entry)
        except OSError as exc:
            print(f"Warning: couldn't add this run to .certo/RUNS.md ({exc}).", file=sys.stderr)

    try:
        messages = run_task(
            resume_from.task if resume_from is not None else task,
            cfg=cfg,
            on_confirm=on_confirm,
            acceptance_checks=acceptance_checks,
            on_awaiting_input=on_awaiting_input,
            on_model_choice=on_model_choice,
            project=args.project,
            save_state=save_state,
            resume_from=resume_from,
            resume_instruction=task if resume_from is not None else None,
            ladder=ladder,
            on_escalate=_confirm_escalation if cfg.interactive else None,
            on_notice=_print_progress,
        )
    except KeyboardInterrupt:
        record_run("interrupted")
        print("\nInterrupted.", file=sys.stderr)
        if save_state:
            print(f"Continue with: {resume_hint}", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean CLI error, not a traceback
        record_run(f"error: {_first_line(str(exc) or type(exc).__name__)}")
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
    outcome = messages.outcome
    record_run(outcome.verification_state, outcome)
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
    if outcome.run_summary is not None:
        print("\nRun summary:")
        for line in outcome.run_summary.format_lines():
            print(f"  {line}")
    if outcome.rungs:
        for line in format_rung_lines(outcome.rungs, outcome.final_rung):
            print(f"  {line}")
    failing = outcome.verification_state in _FAILING_STATES or (
        args.require_verification and outcome.verification_state in _unproven_states()
    )
    if failing and save_state:
        status = os.path.relpath(status_path(cfg.workspace))
        print(f"\nWhere it stopped: {status}. Continue with: {resume_hint}")
    return 1 if failing else 0


def _models_that_ran(cfg, outcome) -> list[str]:
    if outcome.rungs:
        return [r.model for r in outcome.rungs if r.wrote_code]
    summary = outcome.run_summary
    return [m.model for m in summary.models] if summary and summary.models else [cfg.model]


def _run_entry(cfg, ladder, task: str, ended: str, started_at: datetime, outcome) -> RunEntry:
    """What `.certo/RUNS.md` records about this run: the models that really
    ran when the outcome says so, else the ones the settings name."""
    summary = outcome.run_summary if outcome is not None else None
    if outcome is not None and outcome.rungs:
        models = [f"{r.number}. {r.described}: {r.ended}" for r in outcome.rungs]
        note = "escalation" + (
            f", final result from rung {outcome.final_rung}" if outcome.final_rung else ""
        )
    elif ladder is not None:
        models = [f"{i}. {rung.label}" for i, rung in enumerate(ladder.rungs, 1)]
        note = "escalation ladder"
    else:
        models = (
            [m.label for m in summary.models]
            if summary and summary.models
            else [model_label(cfg.model, cfg.reasoning_effort)]
        )
        note = "picked by --auto-model" if cfg.model_selection == "auto" else ""
    return RunEntry(
        task=task, ended=ended, started_at=started_at, models=models, summary=summary, note=note
    )


def _first_line(text: str, limit: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
