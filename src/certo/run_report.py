"""`.certo/reports/<start time>.md`: one page per run, for a person.

Built from the run's JSON result (result.py), the same object `certo --json`
prints, so the page never says something the result doesn't: why the
verdict is what it is, which checks ran, what the agent changed, which
models ran and what it cost. Written by Certo after the run, never by the
agent, when the run keeps state (`CERTO_SAVE_STATE`), next to `RUNS.md`,
which links each run to its page. Model names only, never a key.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .project_state import ensure_state_dir, state_dir
from .run_summary import format_duration

REPORTS_DIR = "reports"
VERDICTS_URL = "https://github.com/alessioricco/certo/blob/main/docs/reference/verdicts.md"

# A list of files, or a check's output, is cut to this many lines.
_MAX_FILES = 50
_MAX_OUTPUT_LINES = 40


def report_relpath(started_at: datetime) -> str:
    """The report's path inside `.certo/`, from the run's start time: the
    same for every milestone of a run, so `RUNS.md` can link it before
    the report is written."""
    return f"{REPORTS_DIR}/{started_at.astimezone(UTC):%Y-%m-%dT%H-%M-%SZ}.md"


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return " ".join(text.split()).replace("|", "\\|")


def _table(header: Sequence[str], rows: list[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines + [""]


def _cost(cost: float, known: bool) -> str:
    return f"${cost:.4f}" + ("" if known else " + unknown")


def _output(text: str) -> list[str]:
    lines = text.rstrip().splitlines()[-_MAX_OUTPUT_LINES:]
    return ["```text", *lines, "```", ""] if lines else []


def _in_project(command: str, workspace: str) -> str:
    """A check's command with the project folder's own path left out."""
    prefix = workspace.rstrip("/\\") + os.sep
    return command.replace(prefix, "") if workspace else command


def _why(result: dict[str, Any]) -> list[str]:
    """The facts behind the verdict, one bullet each."""
    reasons = [f"Stopped: {result['error']}"] if result.get("error") else []
    reasons += [f"Not checked: {note}" for note in result.get("limitations") or []]
    for check in result.get("checks") or []:
        if check["status"] != "passed":
            reasons.append(f"Check `{check['name']}` {check['status']}: {check['summary']}")
    for check in result.get("acceptance") or []:
        if not check["passed"]:
            kind = "Required acceptance check" if check.get("required") else "Acceptance check"
            what = check.get("description") or check.get("path") or check["kind"]
            reasons.append(f"{kind} failed: {what} ({check.get('detail') or 'no detail'})")
    independent = result.get("independent_tests")
    if independent is not None and independent["status"] != "passed":
        reasons.append(f"Independent tests {independent['status']}: {independent['summary']}")
    for change in result.get("check_file_changes") or []:
        how = "deleted" if change.get("deleted") else "changed"
        reasons.append(f"The agent {how} `{change['path']}`, a file the checks rely on")
    if result.get("retries_used"):
        reasons.append(
            f"Certo sent the agent back to fix failing checks {result['retries_used']} time(s)"
        )
    return [f"- {r}" for r in reasons] or ["- Every check Certo ran passed."]


def _milestone_row(m: dict[str, Any]) -> tuple[str, ...]:
    """One milestone: its verdict, and what its own run used and cost
    (empty cells for a milestone that didn't run in this session)."""
    usage = m.get("usage")
    skills = m.get("skills")
    return (
        f"{m['number']}. {m['title']}",
        m["verdict"] or "not started",
        ", ".join(f"`{x['model']}`" for x in usage["models"]) if usage else "",
        (", ".join(skills) or "none") if skills is not None else "",
        f"{usage['prompt_tokens']:,} / {usage['completion_tokens']:,}" if usage else "",
        _cost(usage["cost"], usage["cost_known"]) if usage else "",
    )


def _skills(result: dict[str, Any]) -> list[str]:
    """The skills the run had (for milestones, each one's is in their table)."""
    if any(m.get("skills") is not None for m in result.get("milestones") or []):
        return ["Each milestone's are in the Milestones table above.", ""]
    skills = result.get("skills") or []
    if not skills:
        return ["The run had no skills.", ""]
    return [", ".join(skills), ""]


def _files(result: dict[str, Any]) -> list[str]:
    changed = result.get("files_changed")
    if changed is None:
        return ["Not known: the run stopped before Certo compared the files.", ""]
    lines: list[str] = []
    for kind in ("created", "modified", "deleted"):
        paths = changed.get(kind) or []
        if not paths:
            continue
        lines.append(f"**{kind.capitalize()}** ({len(paths)}):")
        lines += [f"- `{p}`" for p in paths[:_MAX_FILES]]
        if len(paths) > _MAX_FILES:
            lines.append(f"- and {len(paths) - _MAX_FILES} more")
        lines.append("")
    return lines or ["No file changed.", ""]


def _models(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    usage = result.get("usage")
    if usage is not None:
        lines.append(
            f"Time {format_duration(usage['duration_seconds'])} · "
            f"tokens {usage['prompt_tokens']:,} in / {usage['completion_tokens']:,} out · "
            f"cost {_cost(usage['cost'], usage['cost_known'])}"
        )
        lines.append("")
        lines += _table(
            ("Model", "Effort", "Tokens in / out", "Cost"),
            [
                (
                    f"`{m['model']}`",
                    m.get("reasoning_effort") or "default",
                    f"{m['prompt_tokens']:,} / {m['completion_tokens']:,}",
                    _cost(m["cost"], m["cost_known"]),
                )
                for m in usage["models"]
            ],
        )
    rungs = result.get("rungs")
    if rungs:
        lines.append("Escalation, one row per rung:")
        lines.append("")
        lines += _table(
            (
                "Rung",
                "Model",
                "Verdict",
                "Fix attempts",
                "Skills",
                "Time",
                "Tokens in / out",
                "Cost",
                "Final",
            ),
            [
                (
                    r["rung"],
                    f"{r['name']} (`{r['model']}`)",
                    r["verdict"] or r.get("failure"),
                    r["fix_attempts"],
                    ", ".join(r.get("skills") or []) or "none",
                    format_duration(r["duration_seconds"]),
                    f"{r.get('prompt_tokens', 0):,} / {r.get('completion_tokens', 0):,}",
                    _cost(r["cost"], r["cost_known"]),
                    "yes" if r.get("final") else "",
                )
                for r in rungs
            ],
        )
    for decision in result.get("model_decisions") or []:
        lines.append(f"- Chose `{decision['chosen']}` ({decision['kind']}): {decision['reason']}")
    if result.get("model_decisions"):
        lines.append("")
    extra = []
    if usage is not None and usage.get("condensations"):
        extra.append(f"older steps summarized {usage['condensations']} time(s) to fit the window")
    if result.get("tool_call_reminders"):
        extra.append(
            f"{result['tool_call_reminders']} tool-call reminder(s) "
            "(a tool call written as text, or a turn that ended on a plan)"
        )
    if extra:
        lines += ["Also: " + "; ".join(extra) + ".", ""]
    return lines or ["Not known: the run stopped before it used a model.", ""]


def render_report(result: dict[str, Any], started_at: datetime) -> str:
    verdict = result.get("verdict") or "no verdict"
    when = started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    task = result.get("task") or "(no task text)"
    lines = [
        f"# Run report · {verdict}",
        "",
        f"- Started: {when}",
        f"- Certo: {result.get('certo_version')}",
    ]
    if result.get("project"):
        lines.append(f"- Project: {result['project']}")
    lines += ["", "## Task", "", *[f"> {line}" for line in task.strip().splitlines()], ""]

    lines += ["## Why the verdict", ""]
    lines.append(f"**{verdict}**. See [Verdicts]({VERDICTS_URL}) for what it means.")
    lines += ["", *_why(result), ""]

    milestones = result.get("milestones")
    if milestones:
        lines += ["## Milestones", ""]
        lines += _table(
            ("Milestone", "Verdict", "Models", "Skills", "Tokens in / out", "Cost"),
            [_milestone_row(m) for m in milestones],
        )

    checks = result.get("checks") or []
    lines += ["## Checks", ""]
    if checks:
        lines += _table(
            ("Check", "Status", "Command", "Summary"),
            [
                (
                    c["name"],
                    c["status"],
                    f"`{_in_project(c['command'], result.get('workspace') or '')}`",
                    c["summary"],
                )
                for c in checks
            ],
        )
        for check in checks:
            if check["status"] != "passed" and check.get("output_tail"):
                lines += [f"End of `{check['name']}`'s output:", "", *_output(check["output_tail"])]
    else:
        lines += ["Certo ran no check.", ""]
    acceptance = result.get("acceptance") or []
    if acceptance:
        lines += ["Acceptance checks:", ""]
        lines += _table(
            ("Check", "Required", "Passed", "Detail"),
            [
                (
                    a.get("description") or a.get("path") or a["kind"],
                    "yes" if a.get("required") else "no",
                    "yes" if a["passed"] else "no",
                    a.get("detail"),
                )
                for a in acceptance
            ],
        )
    independent = result.get("independent_tests")
    if independent is not None:
        lines.append(
            f"Independent tests, written by `{independent['model']}`: "
            f"{independent['status']}, {independent['summary']}"
        )
        lines.append("")

    lines += ["## Skills", "", *_skills(result)]
    lines += ["## Files changed", "", *_files(result)]
    lines += ["## Models, time and cost", "", *_models(result)]
    return "\n".join(lines).rstrip() + "\n"


def write_report(workspace: str, result: dict[str, Any], started_at: datetime) -> str:
    """Write the run's report and return its path. Raises OSError; the
    caller decides that a failed write never fails the run."""
    ensure_state_dir(workspace)
    path = os.path.join(state_dir(workspace), *report_relpath(started_at).split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_report(result, started_at))
    return path
