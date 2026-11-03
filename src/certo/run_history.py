"""`.certo/RUNS.md` in a project: one entry per `certo` run, never deleted.

`STATUS.md` (project_state.py) holds only the last run, so it can't answer
"which model built this?" a few runs later. This file can: each entry has
the date, the Certo version, the model (or every rung of an escalation),
the verdict, the time and the cost. Written by Certo after the run, never
by the agent; model names only, never a key. Stdlib only.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import __version__
from .project_state import ensure_state_dir, state_dir
from .run_summary import RunSummary, format_duration, model_label

RUNS_FILE = "RUNS.md"

_HEADER = (
    "# Certo runs in this folder\n"
    "\n"
    "One entry per `certo` run, oldest first. Written by Certo, never by the\n"
    "agent. Model names only, never keys.\n"
)


@dataclass(frozen=True)
class RunEntry:
    task: str
    ended: str  # a verdict, or "interrupted", or "error: ..."
    started_at: datetime
    # What ran: one line per model or rung, e.g. "openai/gpt-5.6-luna" or
    # "1. local (ollama/qwen3.8:27b): unchanged, ...".
    models: Sequence[str]
    summary: RunSummary | None = None
    resumed: bool = False
    note: str = ""  # e.g. how the model was chosen
    report: str = ""  # the run's report inside .certo/ (run_report.py), if any


def runs_path(workspace: str) -> str:
    return os.path.join(state_dir(workspace), RUNS_FILE)


def _first_line(text: str, limit: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def render_entry(entry: RunEntry) -> str:
    when = entry.started_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"## {when} · {entry.ended}", ""]
    task = _first_line(entry.task) or "(no task text)"
    lines.append(f"- Task: {task}" + (" (resumed)" if entry.resumed else ""))
    lines.append(f"- Certo: {__version__}")
    if len(entry.models) == 1:
        lines.append(f"- Model: {entry.models[0]}" + (f" ({entry.note})" if entry.note else ""))
    elif entry.models:
        lines.append("- Models:" + (f" {entry.note}" if entry.note else ""))
        lines += [f"  - {m}" for m in entry.models]
    if entry.summary is not None:
        s = entry.summary
        cost = f"${s.total_cost:.4f}" + ("" if s.cost_complete else " + unknown")
        lines.append(
            f"- Time: {format_duration(s.duration_seconds)} · "
            f"Tokens: {s.total_tokens:,} · Cost: {cost}"
        )
    if entry.report:
        lines.append(f"- Report: [{entry.report}]({entry.report})")
    return "\n".join(lines) + "\n"


def append_run(workspace: str, entry: RunEntry) -> None:
    """Add one entry, creating `.certo/` and the file when needed. Raises
    OSError; the caller decides that a failed write never fails the run."""
    ensure_state_dir(workspace)
    path = runs_path(workspace)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(_HEADER)
        f.write("\n" + render_entry(entry))


# The note Certo keeps at the end of a project's README.md, between these
# markers, so a later run can update it instead of adding another one.
README_NOTE_START = "<!-- certo:models -->"
README_NOTE_END = "<!-- /certo:models -->"
_NOTE_MODELS = re.compile(r"`([^`]+)`")


def note_models_in_readme(workspace: str, models: Sequence[str]) -> bool:
    """Add or update the one-line "generated with" note in the project's
    README.md, naming every model that has worked on it, oldest first.
    Does nothing when there is no README.md or no model. Returns whether
    the file changed. Raises OSError."""
    path = os.path.join(workspace, "README.md")
    if not models or not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start, end = text.find(README_NOTE_START), text.find(README_NOTE_END)
    known: list[str] = []
    if 0 <= start < end:
        known = _NOTE_MODELS.findall(text[start:end])
        before, after = text[:start], text[end + len(README_NOTE_END) :]
    else:
        before, after = text, ""
    for model in models:
        if model not in known:
            known.append(model)
    names = ", ".join(f"`{m}`" for m in known)
    note = (
        f"{README_NOTE_START}\n"
        f"*Generated with [Certo](https://github.com/alessioricco/certo), using {names}.*\n"
        f"{README_NOTE_END}"
    )
    # Anything a later edit put after the note stays after it.
    rest = after.strip("\n")
    new_text = f"{before.rstrip()}\n\n{note}\n" + (f"\n{rest}\n" if rest else "")
    if new_text == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return True


def run_entry(
    cfg: Any,
    ladder: Any,
    task: str,
    ended: str,
    started_at: datetime,
    outcome: Any,
    summary: Any = None,
) -> RunEntry:
    """What `.certo/RUNS.md` records about this run: the models that really
    ran when the outcome says so, else the ones the settings name. A run
    that stopped early has no outcome, only the `summary` of its usage."""
    if outcome is not None:
        summary = outcome.run_summary
    if outcome is not None and outcome.rungs:
        models = [f"{r.number}. {r.described}: {r.ended}" for r in outcome.rungs]
        note = "escalation" + (
            f", final result from rung {outcome.final_rung}" if outcome.final_rung else ""
        )
    elif ladder is not None:
        models = [f"{i}. {rung.label}" for i, rung in enumerate(ladder.rungs, 1)]
        note = "escalation ladder"
    else:
        if summary and summary.models:
            models = [m.label for m in summary.models]
        elif cfg.model:
            models = [model_label(cfg.model, cfg.reasoning_effort)]
        else:  # --auto-model stopped before it picked one
            models = []
        note = "picked by --auto-model" if cfg.model_selection == "auto" else ""
    return RunEntry(
        task=task, ended=ended, started_at=started_at, models=models, summary=summary, note=note
    )
