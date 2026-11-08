"""Milestone mode: a task file split into milestones, run and verified one
at a time (`certo --milestones task.md`; see DECISIONS.md, 2026-10-29).

A milestone starts at a `## Milestone N: title` heading; the text before
the first one is context every milestone gets. A milestone may hold one
fenced `acceptance` block, the same JSON array as `--acceptance-checks`.
The block is Certo's, never the agent's: it is taken out of the text the
agent gets.

`.certo/milestones.json` keeps the task file's path and fingerprint, the
titles and each milestone's verdict, never the milestones' text or checks:
the agent can read `.certo/`. `certo --resume` reads the task file again,
refuses it if it changed, and continues the first milestone not verified.
Stdlib only, no SDK import.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .acceptance import AcceptanceCheck, AcceptanceCheckError, parse_acceptance_checks
from .escalation import workspace_listing
from .project_state import STATE_DIR

_PLAN_FILE = "milestones.json"
_HEADING = re.compile(r"^##\s+milestone\s+(\d+)\s*(?::\s*(.*?))?\s*$", re.IGNORECASE)
_FENCE = re.compile(r"^\s*(```+|~~~+)\s*(\S*)")


class MilestoneError(ValueError):
    """A task file that can't be split into milestones. Message is user-facing."""


@dataclass(frozen=True)
class Milestone:
    number: int
    title: str
    text: str
    # The `acceptance` block as written (JSON objects), checked when parsed.
    acceptance: tuple[Mapping[str, object], ...] = ()

    @property
    def label(self) -> str:
        return self.title or f"Milestone {self.number}"

    def checks(self) -> list[AcceptanceCheck]:
        return parse_acceptance_checks(list(self.acceptance))


@dataclass(frozen=True)
class MilestonePlan:
    context: str
    milestones: tuple[Milestone, ...]

    def __len__(self) -> int:
        return len(self.milestones)

    def get(self, number: int) -> Milestone:
        return self.milestones[number - 1]


def _heading_numbers(text: str) -> list[int]:
    """The numbers of the `## Milestone N` headings outside code fences, in
    the order they appear: the same reading `parse_milestones` does."""
    numbers: list[int] = []
    fence: str | None = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            if fence is None:
                fence = match.group(1)
            elif match.group(1).startswith(fence[0]) and len(match.group(1)) >= len(fence):
                fence = None
            continue
        heading = _HEADING.match(line) if fence is None else None
        if heading:
            numbers.append(int(heading.group(1)))
    return numbers


def written_in_milestones(text: str) -> int:
    """How many milestones a task file is written in, for running it in
    milestones without `--milestones`: at least two `## Milestone N`
    headings, numbered 1, 2, 3... in order. 0 for any other file, which a
    run then sends whole, as before (DECISIONS.md)."""
    numbers = _heading_numbers(text)
    if len(numbers) >= 2 and numbers == list(range(1, len(numbers) + 1)):
        return len(numbers)
    return 0


def parse_milestones(text: str) -> MilestonePlan:
    """Split a task file into its milestones, or raise `MilestoneError`."""
    context: list[str] = []
    sections: list[tuple[int, str, list[str]]] = []
    fence: str | None = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            if fence is None:
                fence = match.group(1)
            elif match.group(1).startswith(fence[0]) and len(match.group(1)) >= len(fence):
                fence = None
        heading = _HEADING.match(line) if fence is None and not match else None
        if heading:
            sections.append((int(heading.group(1)), (heading.group(2) or "").strip(), []))
        elif sections:
            sections[-1][2].append(line)
        else:
            context.append(line)
    if not sections:
        raise MilestoneError(
            "no milestone found: with --milestones, each milestone starts with a "
            "heading like '## Milestone 1: title'."
        )
    numbers = [number for number, _, _ in sections]
    if numbers != list(range(1, len(sections) + 1)):
        found = ", ".join(str(n) for n in numbers)
        raise MilestoneError(f"milestones must be numbered 1, 2, 3... in order; found {found}.")
    context_text, context_blocks = _take_acceptance("\n".join(context))
    if context_blocks:
        raise MilestoneError(
            "an acceptance block must be inside a milestone, not before the first one."
        )
    milestones = []
    for number, title, lines in sections:
        body, blocks = _take_acceptance("\n".join(lines))
        if len(blocks) > 1:
            raise MilestoneError(f"milestone {number} has more than one acceptance block.")
        if not body:
            raise MilestoneError(f"milestone {number} has no text: say what it should do.")
        acceptance = _parse_block(number, blocks[0]) if blocks else ()
        milestones.append(Milestone(number, title, body, acceptance))
    return MilestonePlan(context_text, tuple(milestones))


def _take_acceptance(text: str) -> tuple[str, list[str]]:
    """The text without its `acceptance` blocks, and the blocks' contents."""
    kept: list[str] = []
    blocks: list[str] = []
    fence: str | None = None
    in_block = False
    current: list[str] = []
    for line in text.splitlines():
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)
            in_block = match.group(2).lower() == "acceptance"
            if not in_block:
                kept.append(line)
            continue
        if fence is not None and match and match.group(1).startswith(fence[0]):
            if in_block:
                blocks.append("\n".join(current))
                current = []
            else:
                kept.append(line)
            fence, in_block = None, False
            continue
        (current if in_block else kept).append(line)
    if in_block:
        raise MilestoneError("an acceptance block isn't closed with ```.")
    return "\n".join(kept).strip(), blocks


def _parse_block(number: int, raw: str) -> tuple[Mapping[str, object], ...]:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise MilestoneError(
            f"milestone {number}: the acceptance block must be valid JSON: {exc}"
        ) from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise MilestoneError(
            f"milestone {number}: the acceptance block must be a JSON array of check "
            "objects, as for --acceptance-checks."
        )
    try:
        parse_acceptance_checks(data)
    except AcceptanceCheckError as exc:
        raise MilestoneError(f"milestone {number}: {exc}") from exc
    return tuple(data)


def milestone_task(plan: MilestonePlan, number: int, handover: str | None = None) -> str:
    """What the agent gets for milestone `number`: the shared context, the
    milestones done so far by title, what they left (`handover`), and this
    one in full."""
    milestone = plan.get(number)
    total = len(plan)
    parts = [plan.context] if plan.context else []
    parts.append(
        f"This task is done in {total} milestone{'s' if total != 1 else ''}, one at a "
        "time. Certo checks each one before the next starts."
    )
    if number > 1:
        done = "\n".join(f"{m.number}. {m.label}" for m in plan.milestones[: number - 1])
        parts.append(
            "Already done and checked (the work is in the folder; keep it working):\n" + done
        )
    if handover:
        parts.append(handover)
    # --auto-model classifies a milestone by this heading first, and
    # MODEL_DECISIONS.md files its choices under it
    # (model_catalog.current_milestone): keep its shape in step.
    parts.append(f"## Now: milestone {number} of {total}: {milestone.label}\n\n{milestone.text}")
    if number < total:
        parts.append(
            "Do only this milestone: the later ones come in their own runs. When you "
            "finish, Certo runs the project's checks."
        )
    return "\n\n".join(parts)


def is_milestone_task(text: str, plan: MilestonePlan, number: int) -> bool:
    """Whether `text` is what milestone `number` was given, whatever
    handover it had: the handover depends on the folder and the last
    conversation, so a resume in a new session can't rebuild it."""
    return _HANDOVER_SECTION.sub("", text, count=1) == milestone_task(plan, number)


_HANDOVER_SECTION = re.compile(
    r"\n\n## What milestone \d+ left\n.*?(?=\n\n## Now: milestone )", re.S
)
# What a handover lists at most: the folder's files, and the characters
# of the last milestone's own summary.
_HANDOVER_FILES = 40
_HANDOVER_SUMMARY_CHARS = 2000
_COUNTED_MAX_BYTES = 2_000_000


def handover(workspace: str, messages: Sequence[object], finished: int) -> str | None:
    """What milestone `finished` left for the next one, which starts in a
    fresh conversation: the project folder's files with their sizes, and
    the agent's own summary when it finished, marked as not checked. Found by the 0.1.27 local benchmark: a new milestone spent
    most of its time reading the folder and planning again from nothing.
    None when there is nothing to say."""
    files = _file_lines(workspace)
    summary = _finish_summary(messages)
    if not files and not summary:
        return None
    parts = [f"## What milestone {finished} left"]
    if files:
        parts.append("The project folder now (from Certo):\n" + "\n".join(files))
    if summary:
        parts.append(
            f"The agent's own summary at the end of milestone {finished} (not checked "
            "by Certo; the code is what counts):\n\n" + summary
        )
    return "\n\n".join(parts)


def _file_lines(workspace: str) -> list[str]:
    # Shown with "/" on every system, as the agent's tools write paths.
    paths = sorted(
        path.replace(os.sep, "/")
        for path in workspace_listing(workspace)
        if not any(part.startswith(".") for part in path.split(os.sep))
    )
    lines = [f"- {path} ({_size(os.path.join(workspace, path))})" for path in paths]
    if len(lines) > _HANDOVER_FILES:
        more = len(lines) - _HANDOVER_FILES
        lines = [*lines[:_HANDOVER_FILES], f"- ... and {more} more"]
    return lines


def _size(path: str) -> str:
    try:
        size = os.path.getsize(path)
        if size > _COUNTED_MAX_BYTES:
            return f"{size:,} bytes"
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return "unreadable"
    if b"\0" in data:
        return f"{size:,} bytes"
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return f"{lines:,} line{'s' if lines != 1 else ''}"


def _finish_summary(messages: Sequence[object]) -> str | None:
    """The agent's last words, shortened: its last `finish` result, or its
    last message that called no tool (some models end without `finish`).
    Certo's own notices have a name, so they never count."""
    for message in reversed(messages):
        role, name = getattr(message, "role", None), getattr(message, "name", None)
        finish = role == "tool" and name == "finish"
        said = role == "assistant" and name is None and not getattr(message, "tool_calls", None)
        if not (finish or said):
            continue
        text = "".join(getattr(part, "text", "") for part in getattr(message, "content", []) or [])
        text = text.strip()
        if not text:
            continue
        if len(text) > _HANDOVER_SUMMARY_CHARS:
            text = text[:_HANDOVER_SUMMARY_CHARS].rstrip() + " [...]"
        return text
    return None


def whole_task(plan: MilestonePlan) -> str:
    """The task in one go: the context and every milestone under its
    heading, without the acceptance blocks (`certo bench` gives a one-go
    arm the same checks through `acceptance_checks` instead)."""
    parts = [plan.context] if plan.context else []
    for m in plan.milestones:
        heading = f"## Milestone {m.number}" + (f": {m.title}" if m.title else "")
        parts.append(f"{heading}\n\n{m.text}")
    return "\n\n".join(parts)


def checks_up_to(plan: MilestonePlan, number: int) -> list[AcceptanceCheck]:
    """The acceptance checks of milestones 1 to `number`: an earlier
    milestone's check that stops passing is a regression."""
    checks: list[AcceptanceCheck] = []
    for milestone in plan.milestones[:number]:
        checks.extend(milestone.checks())
    return checks


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _next_not_verified(numbers: Sequence[int], verdicts: Mapping[int, str]) -> int | None:
    for number in numbers:
        if verdicts.get(number) != "verified":
            return number
    return None


@dataclass
class SavedMilestones:
    """`.certo/milestones.json`: where the plan came from and how far it
    got. Only titles: the milestones' text and acceptance checks stay in
    the task file, so an agent reading `.certo/` doesn't see them."""

    source: str  # the task file, absolute
    fingerprint: str  # of its text, to notice an edit before a resume
    titles: tuple[str, ...]
    verdicts: dict[int, str] = field(default_factory=dict)
    current: int | None = None  # the milestone running now, or the last one run

    def next_number(self) -> int | None:
        """The first milestone not verified, or None when all are."""
        return _next_not_verified(range(1, len(self.titles) + 1), self.verdicts)


@dataclass
class MilestoneState:
    """A plan in progress: the parsed task file and each milestone's verdict."""

    plan: MilestonePlan
    source: str
    fingerprint: str
    verdicts: dict[int, str] = field(default_factory=dict)
    current: int | None = None

    @classmethod
    def from_text(cls, text: str, source: str) -> MilestoneState:
        """A new plan from the task file's text (raises `MilestoneError`)."""
        return cls(parse_milestones(text), os.path.abspath(source), _fingerprint(text))

    def next_number(self) -> int | None:
        return _next_not_verified([m.number for m in self.plan.milestones], self.verdicts)

    def saved(self) -> SavedMilestones:
        return SavedMilestones(
            self.source,
            self.fingerprint,
            tuple(m.label for m in self.plan.milestones),
            dict(self.verdicts),
            self.current,
        )


def reopen(saved: SavedMilestones) -> MilestoneState:
    """The plan of a saved run, read again from its task file. Raises
    `MilestoneError` when the file is gone or was edited: a plan in
    progress doesn't change under a resume."""
    try:
        with open(saved.source, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as exc:
        raise MilestoneError(
            f"can't read the task file {saved.source} to resume its milestones ({exc})."
        ) from exc
    if _fingerprint(text) != saved.fingerprint:
        raise MilestoneError(
            f"the task file {saved.source} changed since its milestones started. To use "
            "the new version, run it again with --milestones; the milestones start "
            "from the first."
        )
    return MilestoneState(
        parse_milestones(text),
        saved.source,
        saved.fingerprint,
        dict(saved.verdicts),
        saved.current,
    )


def plan_path(workspace: str) -> str:
    return os.path.join(workspace, STATE_DIR, _PLAN_FILE)


def save_state(workspace: str, state: MilestoneState) -> None:
    """Write `.certo/milestones.json` (the caller made `.certo/`)."""
    saved = state.saved()
    data = {
        "source": saved.source,
        "fingerprint": saved.fingerprint,
        "milestones": [
            {"number": n, "title": title, "verdict": saved.verdicts.get(n)}
            for n, title in enumerate(saved.titles, 1)
        ],
        "current": saved.current,
    }
    path = plan_path(workspace)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def load_state(workspace: str) -> SavedMilestones | None:
    """The saved plan, or None when there is none or it can't be read."""
    try:
        with open(plan_path(workspace), encoding="utf-8") as f:
            data = json.load(f)
        milestones = data["milestones"]
        current = data.get("current")
        return SavedMilestones(
            str(data["source"]),
            str(data["fingerprint"]),
            tuple(str(m["title"]) for m in milestones),
            {int(m["number"]): str(m["verdict"]) for m in milestones if m.get("verdict")},
            int(current) if current is not None else None,
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None


def clear_state(workspace: str) -> None:
    """Forget the plan: a run that isn't in milestone mode starts here."""
    try:
        os.remove(plan_path(workspace))
    except OSError:
        pass


def status_lines(workspace: str) -> list[str]:
    """The `## Milestones` section of `STATUS.md`, or nothing outside
    milestone mode."""
    saved = load_state(workspace)
    if saved is None:
        return []
    lines = ["## Milestones", ""]
    for number, title in enumerate(saved.titles, 1):
        verdict = saved.verdicts.get(number)
        if verdict:
            where = f"`{verdict}`"
        elif number == saved.current:
            where = "this run"
        else:
            where = "not started"
        lines.append(f"{number}. {title}: {where}")
    return lines + [""]


def summary_lines(state: MilestoneState) -> Sequence[str]:
    """One line per milestone for the terminal, at the end of a run."""
    lines = []
    for m in state.plan.milestones:
        verdict = state.verdicts.get(m.number) or "not started"
        lines.append(f"{m.number}. {m.label}: {verdict}")
    return lines
