"""`certo-admin` — maintenance CLI: server-mode task store and an LLM
connectivity check (`check-llm`, see llm_check.py). Skills are managed by
`certo skills` (skills_cmd.py).

Talks directly to whatever backend `CERTO_TASK_STORE` selects (via
`build_task_store(load_config())`), the same store `server.py` uses — this
is the CLI half of "delete all records for a project," alongside the REST
`DELETE /tasks`/`DELETE /tasks/{id}` endpoints (see DECISIONS.md
for why both were built). Useful for a `memory`/`sqlite` deployment run
locally as well as a one-off maintenance script pointed at a shared
redis/mysql/postgres store.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from . import __version__
from .config import ConfigError, load_config, override_llm
from .llm_check import DEFAULT_TIMEOUT_SECONDS, check_llm
from .task_store import build_task_store


def _cmd_delete_project(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = build_task_store(cfg)
    try:
        deleted = store.delete_by_project(args.project)
    finally:
        store.close()
    print(f"Deleted {deleted} task(s) for project {args.project!r}.")
    return 0


def _cmd_delete_task(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = build_task_store(cfg)
    try:
        deleted = store.delete(args.task_id)
    finally:
        store.close()
    if not deleted:
        print(f"No task found with id {args.task_id!r}.")
        return 1
    print(f"Deleted task {args.task_id!r}.")
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    cfg = load_config()
    ttl_seconds = args.ttl_seconds if args.ttl_seconds is not None else cfg.task_ttl_seconds
    if ttl_seconds <= 0:
        print(
            "Refusing to purge: TTL is 0 (keep forever). Pass --ttl-seconds to purge "
            "records older than a specific age."
        )
        return 1
    store = build_task_store(cfg)
    try:
        purged = store.purge_expired(ttl_seconds)
    finally:
        store.close()
    print(f"Purged {purged} expired task(s) (ttl_seconds={ttl_seconds}).")
    return 0


# A task's text is cut to this many characters in `list`; `show` has more.
_LISTED_TASK_CHARS = 50


def _cmd_list(args: argparse.Namespace) -> int:
    if args.limit < 0:
        print("--limit must be 0 (all) or more.")
        return 1
    cfg = load_config()
    store = build_task_store(cfg)
    try:
        summaries = store.list_tasks(args.project)
    finally:
        store.close()
    if not summaries:
        where = f" for project {args.project!r}" if args.project is not None else ""
        print(f"No task records{where}.")
        return 0
    shown = summaries[: args.limit] if args.limit else summaries
    rows = [("ID", "PROJECT", "STATUS", "VERDICT", "CREATED (UTC)", "TASK")]
    for s in shown:
        task = " ".join(s.task.split())
        if len(task) > _LISTED_TASK_CHARS:
            task = task[: _LISTED_TASK_CHARS - 3] + "..."
        created = datetime.fromtimestamp(s.created_at, UTC).strftime("%Y-%m-%d %H:%M")
        rows.append((s.id, s.project or "-", s.status, s.verification_state or "-", created, task))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    for row in rows:
        print(
            "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=False)) + "  " + row[-1]
        )
    if len(shown) < len(summaries):
        print(f"({len(shown)} of {len(summaries)} shown, newest first; --limit 0 shows all.)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = build_task_store(cfg)
    try:
        record = store.get(args.task_id)
    finally:
        store.close()
    if record is None:
        print(f"No task found with id {args.task_id!r}.")
        return 1
    print(f"id:                 {record.id}")
    print(f"project:            {record.project}")
    print(f"status:             {record.status}")
    print(f"verification_state: {record.verification_state}")
    print(f"created_at:         {record.created_at}")
    print(f"updated_at:         {record.updated_at}")
    print(f"error:              {record.error}")
    return 0


# --- LLM connectivity check ------------------------------------------------------


def _cmd_check_llm(args: argparse.Namespace) -> int:
    try:
        cfg = override_llm(
            load_config(),
            model=args.model,
            base_url=args.base_url,
            reasoning_effort=args.reasoning_effort,
        )
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Checking {cfg.model}" + (f" at {cfg.base_url}" if cfg.base_url else "") + " ...")
    result = check_llm(cfg, timeout=args.timeout)
    if result.ok:
        print(f"OK — answered in {result.latency_seconds:.1f}s: {result.reply[:200]!r}")
        cost = f"${result.cost:.6f}" if result.cost else "unknown (no pricing data)"
        print(f"Tokens: {result.prompt_tokens} in / {result.completion_tokens} out; cost: {cost}")
        return 0
    print(f"FAILED ({result.error_kind}) after {result.latency_seconds:.1f}s")
    print(f"  {result.error}")
    if result.hint:
        print(f"  Hint: {result.hint}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo-admin",
        description="Maintenance CLI for the Certo server's task store "
        "(CERTO_TASK_STORE-configured backend) and an "
        "LLM connectivity check.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    delete_project = subparsers.add_parser(
        "delete-project",
        help="Delete every task record for a given project identifier.",
    )
    delete_project.add_argument("project", help="Project identifier (as passed to POST /tasks).")
    delete_project.set_defaults(func=_cmd_delete_project)

    delete_task = subparsers.add_parser("delete-task", help="Delete one task record by id.")
    delete_task.add_argument("task_id")
    delete_task.set_defaults(func=_cmd_delete_task)

    purge = subparsers.add_parser(
        "purge",
        help="Manually trigger a TTL-based purge of expired (completed/failed) records.",
    )
    purge.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help="Override CERTO_TASK_TTL_SECONDS for this run. Records whose last update is "
        "older than this are deleted; a value <= 0 refuses to run (use the configured "
        "default instead of accidentally deleting everything).",
    )
    purge.set_defaults(func=_cmd_purge)

    list_cmd = subparsers.add_parser(
        "list", help="List the task records, newest first: id, project, status and verdict."
    )
    list_cmd.add_argument("--project", default=None, help="Only the records of this project.")
    list_cmd.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Show at most this many records (default 50); 0 shows all.",
    )
    list_cmd.set_defaults(func=_cmd_list)

    show = subparsers.add_parser("show", help="Print one task record's summary.")
    show.add_argument("task_id")
    show.set_defaults(func=_cmd_show)

    check = subparsers.add_parser(
        "check-llm",
        help="Send one tiny prompt to the configured LLM and report whether it answers.",
    )
    check.add_argument("--model", default=None, help="Override CERTO_LLM_MODEL for this check.")
    check.add_argument(
        "--base-url", default=None, help="Override CERTO_LLM_BASE_URL for this check."
    )
    check.add_argument(
        "--reasoning-effort",
        default=None,
        help="Override CERTO_LLM_REASONING_EFFORT for this check.",
    )
    check.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Seconds to wait for an answer (default {DEFAULT_TIMEOUT_SECONDS}); no retries.",
    )
    check.set_defaults(func=_cmd_check_llm)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
