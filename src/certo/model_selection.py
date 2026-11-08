"""Orchestration layer for `CERTO_MODEL_SELECTION=auto`, the SDK-touching
half of model_catalog.py's pure data/scoring layer — `runner.py` is the only
caller.

`ModelChain` is the one piece of mutable state `stream_task()` threads
through the initial run and every retry loop: a ranked list of candidates,
computed once (see model_catalog.py's `rank_candidates` docstring for why
this project deliberately never re-scores mid-task), walked forward by
`.advance()` as failures occur. See MANUAL.md "Automatic model selection"
and DECISIONS.md for the full design.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from openhands.sdk import LLM

from .config import Config, override_llm
from .llm import build_llm
from .model_catalog import ModelCatalogEntry, current_milestone, score_entry
from .run_summary import effort_label


@dataclass(frozen=True)
class ModelDecisionRecord:
    """One logged decision — never carries `api_key`/`base_url` (only
    names/scores/reasons), so it's always safe to write to
    `MODEL_DECISIONS.md` or attach to `TaskOutcome`."""

    # "initial" | "escalation_api_failure" | "escalation_quality_failure"
    # (--auto-model), or "ladder" | "climb_quality_failure" |
    # "climb_provider_failure" | "escalation_stop" (--escalate)
    kind: str
    timestamp: str  # ISO-8601 UTC
    task_profile: str
    weights: dict[str, float]
    ranked: tuple[tuple[str, float], ...]  # (name, score), ranked order
    chosen: str
    reason: str
    # How the list is labelled in MODEL_DECISIONS.md: --auto-model ranks
    # candidates by score; an escalation ladder lists rungs by capability.
    list_title: str = "Ranked candidates"
    score_label: str = "score"
    # The chosen model's plain catalog name (`chosen` is its label, with
    # the effort), for code that looks the model up (the benchmark).
    chosen_name: str = ""


# Given the ranked candidates, the recommended index (usually 0, or the
# chain's current index on an escalation), and a human-readable reason —
# returns the index the caller actually wants to use. cli.py supplies a
# real terminal prompt (mirroring _confirm_pending_actions/
# _prompt_for_continuation's self-contained shape); server.py never does
# (no terminal to prompt at, same as ConfirmCallback/OnAwaitingInput).
OnModelChoice = Callable[[list[ModelCatalogEntry], int, str], int]


class ModelChain:
    """A forward-only cursor over one task's ranked model candidates.

    `task_profile`/`weights`/the ranking are fixed at construction — this
    project's model selection deliberately never re-classifies or re-scores
    mid-task, only ever walks the same static list forward. `.current` is
    always a valid candidate; once `.advance()` is exhausted it returns
    `None` and `.current` stays on the last candidate, so callers (see
    `runner.py`) just keep retrying on whatever's current instead of needing
    a special "no more candidates" branch of their own.
    """

    def __init__(
        self,
        ranked: list[ModelCatalogEntry],
        *,
        task_profile: str,
        weights: dict[str, float],
        start_index: int = 0,
    ) -> None:
        if not ranked:
            raise ValueError("ModelChain requires at least one candidate.")
        self._ranked = ranked
        self._task_profile = task_profile
        self._weights = weights
        self._index = start_index
        self.decisions: list[ModelDecisionRecord] = []

    @property
    def candidates(self) -> tuple[ModelCatalogEntry, ...]:
        return tuple(self._ranked)

    @property
    def current(self) -> ModelCatalogEntry:
        return self._ranked[self._index]

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._ranked) - 1

    def _scored_ranking(self) -> tuple[tuple[str, float], ...]:
        return tuple((_label(e), score_entry(e, self._weights)) for e in self._ranked)

    def _record(self, kind: str, reason: str) -> None:
        self.decisions.append(
            ModelDecisionRecord(
                kind=kind,
                timestamp=datetime.now(UTC).isoformat(),
                task_profile=self._task_profile,
                weights=dict(self._weights),
                ranked=self._scored_ranking(),
                chosen=_label(self.current),
                reason=reason,
                chosen_name=self.current.name,
            )
        )

    def record_initial(self, reason: str) -> None:
        """Log the initial pick — called once, after any interactive
        override has already moved `start_index` to what the human chose."""
        self._record("initial", reason)

    def advance(self, *, kind: str, reason: str) -> ModelCatalogEntry | None:
        """Move to the next candidate and log why. Returns the new current
        candidate, or `None` if already on the last one — `.current` is left
        unchanged in that case, not reset or invalidated."""
        if self.exhausted:
            return None
        self._index += 1
        self._record(kind, reason)
        return self.current


def _label(entry: ModelCatalogEntry) -> str:
    """A candidate in MODEL_DECISIONS.md: its name and reasoning effort."""
    return f"{entry.name} (effort {effort_label(entry.reasoning_effort or None)})"


def config_for_entry(cfg: Config, entry: ModelCatalogEntry) -> Config:
    """Return a copy of `cfg` with the LLM fields fully replaced by one
    catalog entry — reuses `override_llm()` exactly as it already exists,
    not a separate builder.

    Passes `""` (not `None`) for a field the entry leaves unset. This
    matters: `override_llm()`'s own contract treats `None` as "leave `cfg`'s
    existing value alone" (right for its per-request-override use case) and
    `""` as "clear it" (via its internal `_clean()`). A catalog entry is a
    *complete*, self-contained model spec, not a partial override — a
    keyless local model (e.g. Ollama) must not silently inherit whatever
    provider API key `cfg` already had for a completely different provider.
    """
    return override_llm(
        cfg,
        model=entry.model,
        api_key=entry.api_key or "",
        base_url=entry.base_url or "",
        reasoning_effort=entry.reasoning_effort or "",
        timeout_seconds=entry.timeout_seconds,
        context_tokens=entry.context_tokens,
    )


def llm_for_entry(cfg: Config, entry: ModelCatalogEntry, *, usage_id: str) -> LLM:
    """Build the `LLM` for one catalog entry — see `config_for_entry()`."""
    return build_llm(config_for_entry(cfg, entry), usage_id=usage_id)


_MILESTONE_SECTION = re.compile(r"^## Milestone (\d+) of \d+: ", re.MULTILINE)


def write_model_decisions(
    workspace: str, decisions: Sequence[ModelDecisionRecord], *, task_text: str = ""
) -> None:
    """(Re)write `MODEL_DECISIONS.md` in the project workspace — same
    placement convention as `skills.write_project_context`'s `AGENTS.md`.

    Always rewrites the *whole* file from the full `decisions` list rather
    than appending incrementally, so calling this again after a later
    decision can't duplicate the file's header or leave it half-written.
    A no-op when `decisions` is empty (auto mode was never engaged).

    For one milestone of a task written in milestones (`task_text` holds
    its `## Now: milestone N of M` heading), the decisions go under a
    `## Milestone N of M: title` section, and the file keeps the sections
    of milestones 1 to N-1 already in it: each milestone is its own run,
    and rewriting the whole file lost the earlier ones' choices. Sections
    from N on are dropped, so a re-run doesn't keep a stale one.
    """
    if not decisions:
        return
    milestone = current_milestone(task_text)
    level = "###" if milestone else "##"
    sections = []
    for d in decisions:
        lines = [f"{level} {d.kind} — {d.timestamp}", "", f"Reason: {d.reason}", ""]
        if d.task_profile:  # escalation ladders don't use task profiles
            lines += [f"Task profile: `{d.task_profile}` (weights: {d.weights})", ""]
        lines.append(f"{d.list_title}:")
        for name, score in d.ranked:
            label = f"**{name}**" if name == d.chosen else name
            lines.append(f"- {label} ({d.score_label} {score:.2f})")
        lines.append("")
        lines.append(f"Chosen: **{d.chosen}**")
        sections.append("\n".join(lines))
    body = "\n\n".join(sections)
    path = os.path.join(workspace, "MODEL_DECISIONS.md")
    if milestone:
        number, total, title = milestone
        earlier = [
            block.rstrip("\n")
            for found, block in _milestone_sections(path)
            if found < number
        ]
        body = "\n\n".join([*earlier, f"## Milestone {number} of {total}: {title}\n\n{body}"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Model Decisions\n\n" + body + "\n")


def _milestone_sections(path: str) -> list[tuple[int, str]]:
    """The `## Milestone N of M:` sections of an existing MODEL_DECISIONS.md,
    as (N, the section's text); none when the file is missing or wasn't
    written by a milestone run."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    starts = list(_MILESTONE_SECTION.finditer(text))
    return [
        (int(m.group(1)), text[m.start() : starts[i + 1].start() if i + 1 < len(starts) else None])
        for i, m in enumerate(starts)
    ]
