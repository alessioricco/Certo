"""Escalation ladders: which models a task climbs through, and in what order.

A ladder is explicit (written under `escalation.ladders` in `models.yaml`)
or derived from the active models' ratings. Both resolve to a
`ResolvedLadder`, printed before a run and written to MODEL_DECISIONS.md.

Derived order (the same for every task):

- capability = the sum of a model's ratings on every axis except the cost
  axis (`escalation.cost_axis`, default `cost`): with the usual axes,
  reasoning + precision + code. Task profiles are not used;
- the best of the cheapest: from the cheapest cost rating to the most
  expensive (a higher `cost` rating means cheaper; no cost rating counts
  as the most expensive), most capable first within one cost rating, then
  the model name, a model is kept only when it is more capable than every
  model kept before it. A model another one beats at the same price or
  less is left out, and named in `skipped`. When no model has a cost
  rating, there is no price to compare: least capable first, then the name;
- at most `max_rungs` rungs: with n kept models and k rungs, rung j
  (0-based) is model number floor(j * (n - 1) / (k - 1) + 0.5), so the
  first rung is the best of the cheapest models, the last rung the most
  capable one, and the ones between are spread evenly.

Pure: no SDK, no network. The run loop lives in runner.py.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .catalog_check import load_checked_catalog, usable_rungs
from .model_catalog import (
    Ladder,
    LadderRung,
    ModelCatalog,
    ModelCatalogEntry,
    capability,
)
from .run_summary import RunSummary, effort_label, format_duration

# Final verdicts that mean "this model couldn't finish the job": the next
# rung gets the task. Never `budget_exhausted`, `cost_exhausted` or
# `confirmation_required` (the user's own limits). `acceptance_failed` only when the ladder opts in.
# `inconclusive` climbs too (0.1.22): a model that wrote code but no tests
# leaves the next one something to finish, and the handoff asks it for the
# missing checks. Two rungs in a row that did no work, or that both ended
# `inconclusive`, stop the climb (runner.py): two models agreeing there is
# nothing to change, or nothing to check, is evidence, and climbing on
# would only spend money.
ESCALATING_VERDICTS = (
    "inconclusive",
    "retry_exhausted",
    "no_progress",
    "timed_out",
    "incomplete",
    "stuck",
    "unchanged",
)


class EscalationError(ValueError):
    """A request for escalation that can't be met. The message is user-facing."""


@dataclass(frozen=True)
class Rung:
    entry: ModelCatalogEntry
    retries: int | None  # None: CERTO_MAX_VERIFY_RETRIES
    reasoning_effort: str | None  # None: the entry's own
    capability: float
    cost_rating: float | None

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def effort(self) -> str | None:
        """The reasoning effort this rung runs at: its own, else its model
        entry's; None when neither sets one."""
        return self.reasoning_effort or self.entry.reasoning_effort or None

    @property
    def label(self) -> str:
        """The name and the effort: a ladder may list one model twice."""
        return f"{self.name} (effort {effort_label(self.effort)})"


@dataclass(frozen=True)
class ResolvedLadder:
    kind: str  # "explicit" | "derived"
    name: str | None  # the ladder's name; None when derived
    rungs: tuple[Rung, ...]
    cost_axis: str
    escalate_on_acceptance_failed: bool = False
    # Plain-language notes on rungs left out (inactive models).
    skipped: tuple[str, ...] = ()
    # Where an explicit ladder was written, for MODEL_DECISIONS.md.
    source: str = "escalation.yaml"

    @property
    def label(self) -> str:
        if self.kind == "derived":
            return "derived ladder (from the ratings)"
        return f"explicit ladder '{self.name}'"

    def escalates_on(self, verdict: str) -> bool:
        if verdict in ESCALATING_VERDICTS:
            return True
        return verdict == "acceptance_failed" and self.escalate_on_acceptance_failed


def spread_indices(n: int, k: int) -> list[int]:
    """Which of n ordered models a k-rung ladder keeps: all of them when
    n <= k, else the first, the last, and evenly spread ones between."""
    if n <= k:
        return list(range(n))
    return [math.floor(j * (n - 1) / (k - 1) + 0.5) for j in range(k)]


def _rung(entry: ModelCatalogEntry, cost_axis: str, retries=None, effort=None) -> Rung:
    return Rung(
        entry=entry,
        retries=retries,
        reasoning_effort=effort,
        capability=capability(entry, cost_axis),
        cost_rating=entry.ratings.get(cost_axis),
    )


def derive_ladder(catalog: ModelCatalog) -> ResolvedLadder:
    settings = catalog.escalation
    active = [m for m in catalog.models if m.activated]
    if not active:
        raise EscalationError("No model is enabled in models.yaml, so there is nothing to climb.")
    scored = [_rung(m, settings.cost_axis) for m in active]
    if all(r.cost_rating is None for r in scored):
        # No prices to compare: least capable first, as no model is cheaper.
        scored.sort(key=lambda r: (r.capability, r.name))
        chosen = tuple(scored[i] for i in spread_indices(len(scored), settings.max_rungs))
        return ResolvedLadder(kind="derived", name=None, rungs=chosen, cost_axis=settings.cost_axis)
    scored.sort(key=lambda r: (-(r.cost_rating or 0.0), -r.capability, r.name))
    kept: list[Rung] = []
    beaten: list[str] = []
    for rung in scored:
        if kept and rung.capability <= kept[-1].capability:
            beaten.append(f"{rung.name} ({kept[-1].name} is at least as capable and costs no more)")
        else:
            kept.append(rung)
    chosen = tuple(kept[i] for i in spread_indices(len(kept), settings.max_rungs))
    return ResolvedLadder(
        kind="derived",
        name=None,
        rungs=chosen,
        cost_axis=settings.cost_axis,
        skipped=tuple(beaten),
    )


def explicit_ladder(catalog: ModelCatalog, ladder: Ladder) -> ResolvedLadder:
    settings = catalog.escalation
    by_name = {m.name: m for m in catalog.models}
    usable = usable_rungs(ladder, catalog)
    skipped = tuple(
        f"{r.model} ({'activated: false' if by_name[r.model].configured else 'not in models.yaml'})"
        for r in ladder.rungs
        if r.model in by_name and not by_name[r.model].activated
    )
    if not usable:
        raise EscalationError(
            f"Ladder '{ladder.name}' has no usable rung: none of its models is enabled in "
            "models.yaml."
        )
    rungs = tuple(
        _rung(by_name[r.model], settings.cost_axis, r.retries, r.reasoning_effort) for r in usable
    )
    return ResolvedLadder(
        kind="explicit",
        name=ladder.name,
        rungs=rungs,
        cost_axis=settings.cost_axis,
        escalate_on_acceptance_failed=ladder.escalate_on_acceptance_failed,
        skipped=skipped,
    )


def ladder_from_models(
    catalog: ModelCatalog, names: Sequence[str], *, name: str = "models"
) -> ResolvedLadder:
    """An explicit ladder from a list of model names (`certo bench` arms)."""
    ladder = Ladder(name=name, rungs=tuple(LadderRung(model=n) for n in names))
    return replace(explicit_ladder(catalog, ladder), source="the benchmark arm's models")


def resolve_ladder(catalog: ModelCatalog, name: str | None) -> ResolvedLadder:
    """The ladder `--escalate [NAME]` uses: the named one; with no name, the
    ladder called `default` when it exists, else a derived one."""
    ladders = catalog.escalation.ladders
    if name:
        if name not in ladders:
            known = ", ".join(sorted(ladders)) or "none (only a derived ladder is available)"
            raise EscalationError(
                f"There is no escalation ladder named '{name}' in escalation.yaml. "
                f"Ladders: {known}."
            )
        return explicit_ladder(catalog, ladders[name])
    if "default" in ladders:
        return explicit_ladder(catalog, ladders["default"])
    return derive_ladder(catalog)


def load_ladder(
    models_file: str,
    models_list_file: str,
    name: str | None,
    *,
    escalation_file: str = "",
    task_profiles_file: str = "",
    on_warning: Callable[[str], None] | None = None,
) -> ResolvedLadder:
    """Find, load and check the model files ("" looks them up, see
    model_files.py), then resolve the ladder. Raises `EscalationError` or
    `ModelCatalogError` (both `ValueError`s) with a message for the user,
    including how to create a missing file."""
    catalog = load_checked_catalog(
        models_file,
        models_list_file,
        task_profiles_file=task_profiles_file,
        escalation_file=escalation_file,
        on_warning=on_warning,
        mode="escalate",
    )
    return resolve_ladder(catalog, name)


def describe_rung(rung: Rung, *, scores: bool) -> str:
    extra = []
    if scores:
        cost = "unrated" if rung.cost_rating is None else f"{rung.cost_rating:g}"
        extra.append(f"capability {rung.capability:g}, cost rating {cost}")
    if rung.retries is not None:
        extra.append(f"{rung.retries} fix attempt(s)")
    extra.append(f"effort {effort_label(rung.effort)}")
    return rung.name + (f" ({'; '.join(extra)})" if extra else "")


def describe_ladder(ladder: ResolvedLadder) -> list[str]:
    """The lines printed before an escalation run starts."""
    lines = [f"Escalation: {ladder.label}, {len(ladder.rungs)} rung(s):"]
    for i, rung in enumerate(ladder.rungs, start=1):
        lines.append(f"  {i}. {describe_rung(rung, scores=ladder.kind == 'derived')}")
    if ladder.skipped:
        lines.append(f"  Skipped: {', '.join(ladder.skipped)}")
    if len(ladder.rungs) == 1:
        lines.append("  Only one rung: this task can't escalate.")
    return lines


# --- One rung's result, and the handoff to the next ------------------------------

# Folders left out of the before/after listing: tools' caches and
# environments, and Certo's own state.
_LISTING_SKIP_DIRS = {
    ".git",
    ".certo",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    # Rust, Maven and Gradle build output, which verification itself writes.
    "target",
    ".gradle",
}
_MAX_LISTED_FILES = 30


def workspace_listing(root: str) -> dict[str, tuple[int, int]]:
    """Every file under `root` (relative path -> size and modification time),
    skipping caches, environments and `.certo/`."""
    listing: dict[str, tuple[int, int]] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _LISTING_SKIP_DIRS)
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            listing[os.path.relpath(path, root)] = (info.st_size, info.st_mtime_ns)
    return listing


@dataclass(frozen=True)
class FileChanges:
    created: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    @classmethod
    def between(
        cls, before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
    ) -> FileChanges:
        return cls(
            created=tuple(sorted(set(after) - set(before))),
            modified=tuple(sorted(p for p in set(after) & set(before) if after[p] != before[p])),
            deleted=tuple(sorted(set(before) - set(after))),
        )


@dataclass(frozen=True)
class RungResult:
    """What one rung did, from facts Certo recorded, never from the model."""

    number: int
    name: str
    model: str
    verdict: str | None  # None when the rung ended in a provider or run failure
    retries_used: int
    duration_seconds: float
    summary: RunSummary | None
    failure: str | None = None  # the provider or run failure, when there was one
    changes: FileChanges = FileChanges()
    failing_checks: tuple[str, ...] = ()  # "name (`command`)"
    reasoning_effort: str | None = None  # None: no effort set
    # How many tool-call reminders this rung's own conversation was sent.
    tool_call_reminders: int = 0

    @property
    def described(self) -> str:
        """The rung's name, model and effort, e.g. "local
        (ollama/qwen3.8:27b, effort default)"."""
        return f"{self.name} ({self.model}, effort {effort_label(self.reasoning_effort)})"

    @property
    def cost(self) -> float:
        return self.summary.total_cost if self.summary is not None else 0.0

    @property
    def cost_known(self) -> bool:
        return self.summary.cost_complete if self.summary is not None else True

    @property
    def ended(self) -> str:
        return self.verdict or "provider or run failure"

    @property
    def did_no_work(self) -> bool:
        """It ended `unchanged`, or `inconclusive` without creating, changing
        or deleting a file (in the 0.1.15 benchmark: a model that wrote its
        tool calls as text). Either way a stronger model may do the task."""
        if self.verdict == "unchanged":
            return True
        changes = self.changes
        return self.verdict == "inconclusive" and not (
            changes.created or changes.modified or changes.deleted
        )

    @property
    def wrote_code(self) -> bool:
        """Whether this rung's model may have written any of the result:
        not a rung that did no work, nor one that stopped at a provider
        error before changing a file (seen live 2026-10-22: a rejected key
        was credited in the project's README)."""
        if self.did_no_work:
            return False
        return self.verdict is not None or _changed_any(self)

    def to_dict(self) -> dict[str, Any]:
        summary = self.summary
        return {
            "rung": self.number,
            "name": self.name,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "verdict": self.verdict,
            "failure": self.failure,
            "fix_attempts": self.retries_used,
            "tool_call_reminders": self.tool_call_reminders,
            "duration_seconds": round(self.duration_seconds, 3),
            "tokens": summary.total_tokens if summary else 0,
            "cost": self.cost,
            "cost_known": self.cost_known,
            "files_created": list(self.changes.created),
            "files_modified": list(self.changes.modified),
            "files_deleted": list(self.changes.deleted),
            "failing_checks": list(self.failing_checks),
        }


def rung_dicts(rungs: Sequence[RungResult], final_rung: int | None) -> list[dict[str, Any]]:
    """The rung list for artifacts and server results: each rung's facts,
    and which one gave the final verdict."""
    return [{**r.to_dict(), "final": r.number == final_rung} for r in rungs]


def _files(paths: tuple[str, ...]) -> str:
    if not paths:
        return "none"
    shown = ", ".join(paths[:_MAX_LISTED_FILES])
    more = len(paths) - _MAX_LISTED_FILES
    return shown + (f" and {more} more" if more > 0 else "")


def _attempts(n: int) -> str:
    return f"{n} fix attempt" + ("" if n == 1 else "s")


# The line before the original task in a handoff message.
HANDOFF_TASK_HEADING = "The task:"


def handoff_task(message: str) -> str | None:
    """The original task inside a handoff message, or None for any other
    message."""
    marker = f"\n\n{HANDOFF_TASK_HEADING}\n\n"
    if marker not in message:
        return None
    return message.split(marker, 1)[1]


def handoff_message(
    task: str, previous: Sequence[RungResult], failing_output: str, *, restarted: bool = False
) -> str:
    """The first message of a rung after the first: the original task, a
    note Certo writes from recorded facts, and the real output of the checks
    that were failing. The files stay in the folder as they were left, or,
    when `restarted`, are back as they were before the first rung."""
    last = previous[-1]
    if restarted and _changed_any(last):
        intro = (
            "Another model already worked on this task in this folder and couldn't "
            "finish it. Certo has undone its changes: the files are back as they were "
            "before any model started. What it did and why it failed is below, so you "
            "can avoid the same mistakes; start from the files as they are now. This "
            "summary was written by Certo from what it recorded, not by a model."
        )
    elif last.verdict == "inconclusive" and not last.did_no_work:
        intro = (
            "Another model already worked on this task in this folder, but left nothing "
            "Certo could check: no test ran, or no check could run. Its "
            "files are still here, exactly as it left them: look at them first, keep "
            "what works, complete the task, and add tests that check what the task asks, "
            "so the work can be verified. This summary was written by Certo from what it "
            "recorded, not by a model."
        )
    elif last.verdict == "inconclusive":
        intro = (
            "Another model already worked on this task in this folder and created or "
            "changed no file, so there was nothing for Certo to check. Do what the task "
            "asks. This summary was written by Certo from what it recorded, not by a model."
        )
    elif last.verdict == "unchanged":
        intro = (
            "Another model already worked on this task in this folder and changed no "
            "file, even when Certo asked it to. The project's checks pass, but they "
            "passed before it started too, so they don't show the task is done. Do what "
            "the task asks; if it truly needs no change, say why. This summary was "
            "written by Certo from what it recorded, not by a model."
        )
    elif last.verdict is None and not _changed_any(last):
        intro = (
            "Another model was given this task first, but it stopped at a provider "
            "error before it created or changed any file. Do what the task asks. This "
            "summary was written by Certo from what it recorded, not by a model."
        )
    else:
        intro = (
            "Another model already worked on this task in this folder and couldn't "
            "finish it. Its files are still here, exactly as it left them: look at them "
            "first, keep what works, and complete the task. This summary was written by "
            "Certo from what it recorded, not by a model."
        )
    lines = [
        intro,
        "",
        f"- Model: {last.described}",
        f"- Result: {last.ended}" + (f" ({last.failure})" if last.failure else ""),
        f"- Fix attempts after failed checks: {last.retries_used}",
        f"- Files it created: {_files(last.changes.created)}",
        f"- Files it changed: {_files(last.changes.modified)}",
        f"- Files it deleted: {_files(last.changes.deleted)}",
        f"- Checks failing when it stopped: {', '.join(last.failing_checks) or 'none'}",
    ]
    if len(previous) > 1:
        earlier = "; ".join(f"{r.name}: {r.ended}" for r in previous[:-1])
        lines.append(f"- Earlier models on this task: {earlier}")
    lines += ["", HANDOFF_TASK_HEADING, "", task.strip()]
    if failing_output:
        heading = (
            "Output of the checks that were failing, on its version (now undone):"
            if restarted and _changed_any(last)
            else "Output of the checks that were failing:"
        )
        lines += ["", heading, "", failing_output]
    return "\n".join(lines)


def _changed_any(result: RungResult) -> bool:
    changes = result.changes
    return bool(changes.created or changes.modified or changes.deleted)


# The SDK's provider errors (`openhands.sdk.llm.exceptions`), by class name,
# so this module needs no SDK import.
_PROVIDER_FAILURES = {
    "LLMAuthenticationError": "the provider rejected its API key",
    "LLMRateLimitError": "the provider refused the request (out of credit, or rate limited)",
    "LLMTimeoutError": "the provider didn't answer in time",
    "LLMServiceUnavailableError": "the provider couldn't be reached",
}


def failure_reason(failure: str | None) -> str | None:
    """A plain reason for a rung's provider failure, with the error's class
    name, or None for an error with no known meaning. `failure` is
    "ErrorClass: message", as `RungResult.failure` records it."""
    name = (failure or "").split(":", 1)[0].strip()
    reason = _PROVIDER_FAILURES.get(name)
    return f"{reason} ({name})" if reason else None


def climb_line(previous: RungResult, nxt: Rung, number: int, total: int) -> str:
    if previous.verdict is None:
        reason = failure_reason(previous.failure)
        why = (
            f"failed: {reason}"
            if reason
            else f"failed at the provider or run level ({previous.failure})"
        )
    elif previous.verdict == "inconclusive" and previous.did_no_work:
        why = "ended inconclusive without changing a file"
    elif previous.verdict == "inconclusive":
        why = "ended inconclusive: it changed files, but nothing could be checked"
    else:
        why = f"ended {previous.verdict} after {_attempts(previous.retries_used)}"
    # One model on two rungs, at two efforts: the names alone would read
    # "qwen ...; escalating to qwen".
    same = previous.name == nxt.name
    before = previous.name + (
        f" (effort {effort_label(previous.reasoning_effort)})" if same else ""
    )
    after = nxt.label if same else nxt.name
    return f"Certo: {before} {why}; escalating to {after} (rung {number} of {total})."


def format_rung_lines(rungs: Sequence[RungResult], final_rung: int | None) -> list[str]:
    """The per-rung part of the run summary."""
    lines = ["Rungs:"]
    for r in rungs:
        tokens = r.summary.total_tokens if r.summary else 0
        cost = f"${r.cost:.4f}" if r.cost_known else f"${r.cost:.4f} + unknown"
        lines.append(
            f"  {r.number}. {r.described}: {r.ended}, {_attempts(r.retries_used)}, "
            f"{format_duration(r.duration_seconds)}, {tokens:,} tokens, {cost}"
        )
    if final_rung is not None:
        final = next(r for r in rungs if r.number == final_rung)
        lines.append(f"Final result from rung {final_rung} ({final.name}).")
    return lines
