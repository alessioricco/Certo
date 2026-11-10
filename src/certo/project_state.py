"""The `.certo/` folder in a project: what the last command-line run did, so
`certo --resume` can continue it after an interruption or a failed verdict.

Two things live there:

- `conversations/<id>/`: the SDK's own saved conversation (written by
  `Conversation(persistence_dir=...)`), which gives a resumed run the
  agent's exact context. Only for local runs: the SDK refuses a
  persistence folder for a Docker (remote) conversation.
- `run.json` and `STATUS.md`: the same record twice, for Certo and for
  people. Written by Certo, never by the agent, so the verdict and the
  failing checks in it can be trusted. A resume also gives `STATUS.md`'s
  text to the agent, which is all it gets when the saved conversation
  can't be used (Docker, or a conversation the SDK can't load).

The folder holds its own `.gitignore` (`*`), so git ignores it without the
project's `.gitignore` being edited. Only the last run is kept. Stdlib only.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime

from .run_summary import model_label

STATE_DIR = ".certo"
_RECORD_FILE = "run.json"
_STATUS_FILE = "STATUS.md"
_CONVERSATIONS_DIR = "conversations"
# The end of each failing check's output kept in the record: enough to see
# the error, small enough to read in STATUS.md and to send to the agent.
_OUTPUT_TAIL_CHARS = 2000

# What `status` can be. "running" on disk with no Certo process means the
# run was killed before it could record anything else.
RUN_STATUSES = ("running", "finished", "interrupted", "error")


@dataclass
class CheckRecord:
    name: str
    status: str
    command: str
    output_tail: str = ""


@dataclass
class RunRecord:
    """The last command-line run in a project. Never holds a secret: the
    model name, never its key."""

    task: str
    conversation_id: str  # uuid hex
    model: str
    execution: str
    started_at: str
    updated_at: str
    status: str = "running"
    verdict: str | None = None
    retries_used: int = 0
    checks: list[CheckRecord] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    error: str | None = None
    resumes: int = 0
    reasoning_effort: str | None = None  # None: no effort set
    # Stopped by a step, time or cost limit with passing checks: verified,
    # but maybe unfinished (TaskOutcome.cut_short).
    cut_short: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> RunRecord:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["checks"] = [CheckRecord(**c) for c in values.get("checks", [])]
        return cls(**values)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def state_dir(workspace: str) -> str:
    return os.path.join(workspace, STATE_DIR)


def conversations_dir(workspace: str) -> str:
    return os.path.join(state_dir(workspace), _CONVERSATIONS_DIR)


def status_path(workspace: str) -> str:
    return os.path.join(state_dir(workspace), _STATUS_FILE)


def ensure_state_dir(workspace: str) -> str:
    """Create `.certo/` with its self-ignoring `.gitignore`, and return it."""
    path = state_dir(workspace)
    os.makedirs(path, exist_ok=True)
    gitignore = os.path.join(path, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write("# Certo's run state; see `certo --resume`.\n*\n")
    return path


def load_record(workspace: str) -> RunRecord | None:
    """The saved record, or None when there is none or it can't be read."""
    try:
        with open(os.path.join(state_dir(workspace), _RECORD_FILE), encoding="utf-8") as f:
            return RunRecord.from_dict(json.load(f))
    except (OSError, ValueError, TypeError):
        return None


def save_record(workspace: str, record: RunRecord) -> None:
    """Write `run.json` and `STATUS.md`, each replaced atomically."""
    path = ensure_state_dir(workspace)
    record.updated_at = now()
    _write_atomic(os.path.join(path, _RECORD_FILE), json.dumps(asdict(record), indent=2) + "\n")
    from .milestones import status_lines  # milestones.py imports this module

    _write_atomic(os.path.join(path, _STATUS_FILE), render_status(record, status_lines(workspace)))


def drop_other_conversations(workspace: str, keep: str) -> None:
    """Delete saved conversations other than `keep`: only the last run is
    kept, and each one can be several megabytes."""
    root = conversations_dir(workspace)
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if name != keep:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def has_saved_conversation(workspace: str, conversation_id: str) -> bool:
    return os.path.isfile(
        os.path.join(conversations_dir(workspace), conversation_id, "base_state.json")
    )


def checks_from_outcomes(checks) -> list[CheckRecord]:
    """`CheckRecord`s from `CheckOutcome`s (duck-typed: this module doesn't
    import the verification code). Output is kept only for a check that
    didn't pass."""
    records = []
    for check in checks:
        tail = ""
        if check.status in ("failed", "timed_out"):
            tail = check.output.strip()[-_OUTPUT_TAIL_CHARS:]
        records.append(CheckRecord(check.name, check.status, check.command, tail))
    return records


def _status_line(record: RunRecord) -> str:
    if record.status == "running":
        return "running, or stopped before Certo could record how it ended"
    if record.status == "interrupted":
        return "interrupted"
    if record.status == "error":
        return f"stopped with an error: {record.error}"
    if record.cut_short:
        return f"stopped at a limit before the agent said it was done, verdict `{record.verdict}`"
    return f"finished, verdict `{record.verdict}`"


def render_status(record: RunRecord, milestones: list[str] | None = None) -> str:
    """`STATUS.md`; `milestones` is the milestone list in milestone mode."""
    lines = [
        "# Certo run status",
        "",
        (
            "Written by Certo after each step of the last run in this folder. "
            "`certo --resume` continues from here."
        ),
        "",
        f"- Status: {_status_line(record)}",
        f"- Model: {model_label(record.model, record.reasoning_effort)}",
        f"- Started: {record.started_at}",
        f"- Updated: {record.updated_at}",
        f"- Verification retries used: {record.retries_used}",
    ]
    if record.resumes:
        lines.append(f"- Resumed: {record.resumes} time(s)")
    lines += [""] + list(milestones or ())
    lines += ["## Task", "", record.task.strip(), ""]
    if record.checks:
        lines += ["## Last verification", ""]
        for check in record.checks:
            command = f" (`{check.command}`)" if check.command else ""
            lines.append(f"- `{check.status}` {check.name}{command}")
        for check in record.checks:
            if check.output_tail:
                lines += ["", f"### {check.name} output (end)", "", "```text", check.output_tail]
                lines += ["```"]
        lines.append("")
    if record.limitations:
        lines += ["## Not checked", ""] + [f"- {note}" for note in record.limitations] + [""]
    return "\n".join(lines)


def resume_message(record: RunRecord, instruction: str | None, *, has_context: bool) -> str:
    """The message that restarts the agent.

    With the saved conversation (`has_context`), the agent already knows the
    task, so it gets the status and the instruction. Without it, this message
    is everything the agent knows, so it starts with the task itself.
    """
    parts = []
    if has_context:
        parts.append(
            "This task is being resumed. Certo's record of how the last run ended "
            "is below. Check the files as they are now, then continue the task "
            "until it is complete and its checks pass."
        )
    else:
        parts.append(
            "Continue a task that an earlier run started in this folder. The earlier "
            "conversation isn't available; the files it left are. Certo's record of "
            "where it stopped is below. Look at the existing files first, then "
            "complete the task and make its checks pass."
        )
    if instruction:
        parts.append(f"Additional instruction from the user:\n{instruction.strip()}")
    parts.append(render_status(record))
    return "\n\n".join(parts)


def _write_atomic(path: str, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
