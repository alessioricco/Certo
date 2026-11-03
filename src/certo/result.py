"""A run's result as JSON: the one format `certo --json`, the server and the
MCP server return (DECISIONS.md, "The MCP server: every command, on a shared
core"). The fields are documented in docs/reference/json-result.md.

`RESULT_VERSION` goes up when a field is renamed, removed or changes meaning;
a new field doesn't change it. Nothing here holds an API key: the result is
built from the outcome and the run's facts, never from the settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from . import __version__
from .escalation import rung_dicts

if TYPE_CHECKING:  # the SDK loads with runner; `certo --help` mustn't wait for it
    from .runner import TaskOutcome

RESULT_VERSION = 1

# A check's output is cut to its last characters: enough for the failing
# tests and the error, not the whole log.
OUTPUT_TAIL_CHARS = 4000


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_TAIL_CHARS else text[-OUTPUT_TAIL_CHARS:]


def check_dict(check: Any) -> dict[str, Any]:
    """One check (verification.CheckOutcome) as the result shows it."""
    return {
        "name": check.name,
        "command": check.command,
        "primary": check.primary,
        "status": check.status,
        "exit_code": check.exit_code,
        "summary": check.summary,
        "output_tail": _tail(check.output),
    }


def _independent(found: Any) -> dict[str, Any] | None:
    if found is None:
        return None
    return {
        "status": found.status,
        "summary": found.summary,
        "model": found.model,
        "output_tail": _tail(found.output),
        "sets": [{"status": s.status, "summary": s.summary} for s in found.sets],
    }


def _usage(outcome: TaskOutcome) -> dict[str, Any] | None:
    summary = outcome.run_summary
    if summary is None:
        return None
    return {
        "duration_seconds": round(summary.duration_seconds, 1),
        "total_tokens": summary.total_tokens,
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "cache_read_tokens": summary.cache_read_tokens,
        "cost": round(sum(m.cost for m in summary.models), 6),
        "cost_known": all(m.cost_known for m in summary.models),
        "condensations": summary.condensations,
        "models": [
            {
                "model": m.model,
                "reasoning_effort": m.reasoning_effort,
                "prompt_tokens": m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
                "cache_read_tokens": m.cache_read_tokens,
                "cost": round(m.cost, 6),
                "cost_known": m.cost_known,
            }
            for m in summary.models
        ],
    }


def _decisions(outcome: TaskOutcome) -> list[dict[str, Any]] | None:
    """How --auto-model and --escalate chose each model, as MODEL_DECISIONS.md
    tells it; no key or base URL is in a decision."""
    if not outcome.model_decisions:
        return None
    return [
        {
            "kind": d.kind,
            "timestamp": d.timestamp,
            "task_profile": d.task_profile or None,
            "weights": dict(d.weights),
            # --auto-model ranks by a weighted "score"; a ladder by "capability".
            "scored_by": d.score_label,
            "candidates": [{"name": name, "score": score} for name, score in d.ranked],
            "chosen": d.chosen,
            "reason": d.reason,
        }
        for d in outcome.model_decisions
    ]


def run_result(
    outcome: TaskOutcome | None,
    *,
    task: str,
    workspace: str,
    project: str | None = None,
    milestones: Sequence[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """The JSON result of one run. `outcome` is None when the run stopped
    with an error or was interrupted; `error` then says why."""
    result: dict[str, Any] = {
        "result_version": RESULT_VERSION,
        "certo_version": __version__,
        "task": task,
        "project": project,
        "workspace": workspace,
        "verdict": None,
        "limitations": [],
        "checks": [],
        "acceptance": [],
        "retries_used": 0,
        "tool_call_reminders": 0,
        "independent_tests": None,
        "check_file_changes": [],
        "files_changed": None,
        "usage": None,
        "rungs": None,
        "model_decisions": None,
        "milestones": list(milestones) if milestones is not None else None,
        "error": error,
    }
    if outcome is None:
        return result
    result.update(
        verdict=outcome.verification_state,
        limitations=list(outcome.completion_contract.limitations),
        checks=[check_dict(c) for c in outcome.checks],
        acceptance=[
            {**asdict(r.check), "passed": r.passed, "detail": r.detail}
            for r in outcome.acceptance_results
        ],
        retries_used=outcome.retries_used,
        tool_call_reminders=outcome.tool_call_reminders,
        independent_tests=_independent(outcome.independent_tests),
        check_file_changes=[asdict(c) for c in outcome.check_file_changes],
        files_changed=(
            {
                "created": list(outcome.files_changed.created),
                "modified": list(outcome.files_changed.modified),
                "deleted": list(outcome.files_changed.deleted),
            }
            if outcome.files_changed is not None
            else None
        ),
        usage=_usage(outcome),
        rungs=rung_dicts(outcome.rungs, outcome.final_rung) if outcome.rungs else None,
        model_decisions=_decisions(outcome),
    )
    return result
