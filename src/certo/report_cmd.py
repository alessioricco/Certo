"""`certo report [PATH] [--note TEXT]`: the last run's problems in one
Markdown file, for the user to hand to Certo's maintainers (a GitHub issue,
or a session working on Certo).

Built only from what `.certo/` already holds after a run: `run.json` (the
model and the settings that matter), the run's report page (run_report.py:
the verdict and why, the checks with the end of their output, the files
changed, the check files the agent edited, the models and the cost, and
Certo's notices), and the errors the SDK saved in the run's conversation
(provider failures, tool errors, rejected actions). Nothing new is
recorded, and no model is called.

The file never holds a key: every value that looks like one (those the
settings files and `models.yaml` hold, and the usual key shapes) is
replaced with `[hidden]` before the file is written, and the file says so.
The user still reads it before sharing: it holds the task and the checks'
output.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from . import __version__
from .project_state import load_record, state_dir, status_line
from .run_report import REPORTS_DIR
from .run_summary import format_duration, model_label

REPORT_FILE = "certo-report.md"
HIDDEN = "[hidden]"

# A saved conversation's events, and the kinds that are errors.
_EVENTS_DIR = "events"
_ERROR_KINDS = ("ConversationErrorEvent", "AgentErrorEvent", "UserRejectObservation")
_MAX_ERRORS = 50
_MAX_ERROR_CHARS = 600

# A setting whose name says it holds a secret. Its value is hidden only when
# it could be one: long enough, with a letter (not a number like a budget).
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)
_MIN_SECRET_CHARS = 12
# Key shapes hidden wherever they appear, known to Certo or not.
_KEY_SHAPES = re.compile(
    r"\bsk-[A-Za-z0-9_-]{16,}"  # OpenAI, Anthropic (sk-ant-...), others
    r"|\bAIza[0-9A-Za-z_-]{30,}"  # Google
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"  # GitHub
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"  # Slack
    r"|\bAKIA[0-9A-Z]{16}\b"  # AWS access key id
    r"|\bhf_[A-Za-z0-9]{20,}"  # Hugging Face
    r"|(?<=Bearer )[A-Za-z0-9._~+/-]{16,}=*"
)


def _could_be_secret(value: str) -> bool:
    value = value.strip()
    return len(value) >= _MIN_SECRET_CHARS and any(c.isalpha() for c in value)


def secrets_in_settings(environ: Mapping[str, str]) -> set[str]:
    """The values of settings whose names say they hold a secret."""
    return {
        v.strip()
        for k, v in environ.items()
        if isinstance(v, str) and _SECRET_NAME.search(k) and _could_be_secret(v)
    }


def _api_keys_in(data: object) -> Iterable[str]:
    """Every `api_key` written out in a parsed YAML file (a `${NAME}`
    reference is not a key: its value is in the settings)."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "api_key" and isinstance(value, str) and "${" not in value:
                yield value.strip()
            else:
                yield from _api_keys_in(value)
    elif isinstance(data, list):
        for item in data:
            yield from _api_keys_in(item)


def secrets_in_models_files(project: str) -> set[str]:
    """The keys written out in the `models.yaml` files a run in `project`
    reads (every layer). Never printed: only used to hide them."""
    import yaml

    from .model_catalog import MODELS_FILE
    from .model_files import find_layers, layers_of

    try:
        found = find_layers(MODELS_FILE, os.environ.get("CERTO_MODELS_FILE", ""), project)
        paths = layers_of(found)
    except Exception:  # noqa: BLE001 - a broken setup still gets a report
        return set()
    keys: set[str] = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            continue
        keys.update(k for k in _api_keys_in(data) if _could_be_secret(k))
    return keys


def known_secrets(project: str) -> set[str]:
    """Every value the report must not show: the secret settings from the
    environment and the settings files (the project's `.env`, this folder's
    and the user's), and the keys in `models.yaml`."""
    from .config import load_settings_files

    environ = dict(os.environ)
    for dotenv in (os.path.join(project, ".env"), ".env"):
        try:
            load_settings_files(dotenv_path=dotenv, environ=environ)
        except Exception:  # noqa: BLE001 - an unreadable file hides nothing more
            pass
    return secrets_in_settings(environ) | secrets_in_models_files(project)


def hide_secrets(text: str, secrets: Iterable[str]) -> tuple[str, int]:
    """`text` with each secret and each key-shaped value replaced by
    `[hidden]`, and how many were replaced."""
    count = 0
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret and secret in text:
            count += text.count(secret)
            text = text.replace(secret, HIDDEN)
    text, shaped = _KEY_SHAPES.subn(HIDDEN, text)
    return text, count + shaped


def latest_report_page(project: str) -> str | None:
    """The newest run report page in `.certo/reports/` (named by start time)."""
    pages = sorted(glob.glob(os.path.join(state_dir(project), REPORTS_DIR, "*.md")))
    return pages[-1] if pages else None


def _one_line(text: str, limit: int = _MAX_ERROR_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sdk_errors(project: str, conversation_id: str) -> list[str]:
    """The errors the SDK saved in the run's conversation, oldest first:
    provider and conversation errors, tool errors, rejected actions."""
    if not conversation_id:
        return []
    folder = os.path.join(state_dir(project), "conversations", conversation_id, _EVENTS_DIR)
    errors: list[str] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                event = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("kind") not in _ERROR_KINDS:
            continue
        when = str(event.get("timestamp") or "")[:19].replace("T", " ")
        kind = event["kind"]
        if kind == "ConversationErrorEvent":
            what = f"{event.get('code') or 'error'}: {_one_line(event.get('detail') or '')}"
        elif kind == "AgentErrorEvent":
            what = f"tool `{event.get('tool_name') or '?'}`: {_one_line(event.get('error') or '')}"
        else:
            reason = _one_line(event.get("rejection_reason") or "")
            what = f"action rejected, tool `{event.get('tool_name') or '?'}`: {reason}"
        errors.append(f"{when} · {kind} · {what}")
    if len(errors) > _MAX_ERRORS:
        left_out = len(errors) - _MAX_ERRORS
        errors = [f"(the first {left_out} are left out)"] + errors[-_MAX_ERRORS:]
    return errors


def _demoted(page: str) -> list[str]:
    """The report page with each heading one level down, so it sits under
    this file's own; lines in code blocks are left as they are."""
    lines, in_code = [], False
    for line in page.rstrip().splitlines():
        if line.startswith(("```", "~~~")):
            in_code = not in_code
        lines.append("#" + line if not in_code and line.startswith("#") else line)
    return lines


def _seconds(value: int) -> str:
    return format_duration(value) if value else "not recorded"


def render(project: str, note: str = "", now: datetime | None = None) -> str | None:
    """The report's text, before secrets are hidden; None when `project`
    has no recorded run."""
    record = load_record(project)
    page = latest_report_page(project)
    if record is None and page is None:
        return None
    now = now or datetime.now(UTC)
    lines = [
        "# Certo report",
        "",
        f"Written by `certo report` on {now:%Y-%m-%d %H:%M UTC} about the last run in "
        f"`{os.path.basename(os.path.abspath(project))}`, from what Certo recorded in its "
        "`.certo/` folder. Values that look like keys are replaced with "
        f"`{HIDDEN}`. It still holds the task and the checks' output: read it "
        "before you share it.",
        "",
    ]
    if note.strip():
        lines += ["## Note", "", *[f"> {line}" for line in note.strip().splitlines()], ""]
    lines += [
        "## Certo and this computer",
        "",
        f"- Certo now: {__version__}",
        f"- Python: {platform.python_version()}",
        f"- System: {platform.system()} {platform.release()} ({platform.machine()})",
        "",
    ]
    if record is not None:
        task = record.task.strip().splitlines()
        lines += [
            "## The run",
            "",
            f"- Task: {task[0] if task else '(no task text)'}",
            f"- How it ended: {status_line(record)}",
            f"- Model: {model_label(record.model, record.reasoning_effort)}",
            f"- Model selection: {record.model_selection}"
            + (f" (ladder `{record.escalation_ladder}`)" if record.escalation_ladder else ""),
            f"- Execution: {record.execution}",
            f"- Time budget: {_seconds(record.max_task_seconds)}",
            f"- Step limit: {record.max_iterations or 'not recorded'}",
            f"- Verification retries used: {record.retries_used}",
            f"- Resumed: {record.resumes} time(s)",
            f"- Started: {record.started_at} · last update: {record.updated_at}",
        ]
        if record.cut_short:
            lines.append(
                "- Stopped by a step, time or cost limit before the agent said it was done"
            )
        lines.append("")
        errors = sdk_errors(project, record.conversation_id)
        lines += ["## Errors the SDK recorded", ""]
        if errors:
            lines += [f"- {e}" for e in errors]
        elif os.path.isdir(
            os.path.join(state_dir(project), "conversations", record.conversation_id)
        ):
            lines.append("None.")
        else:
            lines.append(
                "Not known: the run's conversation wasn't saved (a Docker run, or removed)."
            )
        lines.append("")
    lines += ["## The run's report", ""]
    if page is None:
        lines += ["No report page was written for this run.", ""]
    else:
        try:
            with open(page, encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            lines += [f"The report page couldn't be read ({exc}).", ""]
        else:
            lines += [f"From `.certo/{REPORTS_DIR}/{os.path.basename(page)}`.", ""]
            lines += [*_demoted(text), ""]
    return "\n".join(lines).rstrip() + "\n"


def build_report_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo report",
        description=(
            "Write the last run's verdict, settings, notices and errors to one Markdown "
            "file, with keys hidden, to share with Certo's maintainers."
        ),
    )
    parser.add_argument(
        "path", nargs="?", default=".", help="Project directory (default: current directory)."
    )
    parser.add_argument("--note", default="", help="Your own words, added at the top.")
    parser.add_argument(
        "--output",
        metavar="FILE",
        help=f"Where to write it (default: .certo/{REPORT_FILE} in the project).",
    )
    return parser


def report_main(argv: list[str]) -> int:
    args = build_report_parser().parse_args(argv)
    project = os.path.abspath(args.path)
    if not os.path.isdir(project):
        print(f"Error: {args.path} is not a directory", file=sys.stderr)
        return 1
    text = render(project, args.note)
    if text is None:
        print(
            f"No run recorded in {project}. Certo records each run in its .certo/ folder "
            "(CERTO_SAVE_STATE, on by default).",
            file=sys.stderr,
        )
        return 1
    text, hidden = hide_secrets(text, known_secrets(project))
    path = os.path.abspath(args.output or os.path.join(state_dir(project), REPORT_FILE))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        print(f"Error: couldn't write {path} ({exc})", file=sys.stderr)
        return 1
    print(f"Report: {path}")
    if hidden:
        print(f"{hidden} value(s) that looked like keys were replaced with {HIDDEN}.")
    print("Read it before you share it: it holds the task and the checks' output.")
    return 0
