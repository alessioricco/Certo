"""Milestone mode's task-file parsing and saved plan (milestones.py). No LLM."""

from __future__ import annotations

import pytest

from certo.milestones import (
    MilestoneError,
    MilestoneState,
    checks_up_to,
    clear_state,
    handover,
    is_milestone_task,
    load_state,
    milestone_task,
    parse_milestones,
    reopen,
    save_state,
    status_lines,
    written_in_milestones,
    summary_lines,
)
from types import SimpleNamespace

from certo.project_state import RunRecord, ensure_state_dir, save_record, status_path

TASK = """# Todo app
A command-line todo list in Python.

## Milestone 1: storage
Add and list items, saved to todo.json.
```acceptance
[{"kind": "file_exists", "path": "todo.py"}]
```

## Milestone 2: due dates
Items can have a due date.
```python
# ## Milestone 9: not a heading, it's in a code block
```
"""


def test_a_task_file_splits_into_context_and_milestones():
    plan = parse_milestones(TASK)

    assert plan.context == "# Todo app\nA command-line todo list in Python."
    assert [(m.number, m.title) for m in plan.milestones] == [(1, "storage"), (2, "due dates")]
    assert plan.get(1).text == "Add and list items, saved to todo.json."
    assert plan.get(1).checks()[0].path == "todo.py"
    assert plan.get(2).acceptance == ()


def test_a_heading_inside_a_code_block_is_text():
    plan = parse_milestones(TASK)

    assert len(plan) == 2
    assert "## Milestone 9" in plan.get(2).text


def test_the_acceptance_block_is_not_in_the_agents_text():
    text = milestone_task(parse_milestones(TASK), 1)

    assert "acceptance" not in text
    assert "todo.py" not in text


def test_a_heading_needs_no_title():
    plan = parse_milestones("## Milestone 1\nDo it.")

    assert plan.get(1).label == "Milestone 1"


# Live 2026-11-10: a task file with "## M0 — Plan ..." to "## M9 — ..."
# headings ran as one task, on one budget of steps.
SHORT_FORM = """# A game

Rules for every milestone.

## M0 \u2014 Plan, Tech Stack Decision & Foundations
Write PLAN.md.

## M1 \u2014 Engine Core
Build the loop.

## M2 - Player & Shooting
Add the ship.
"""


def test_short_headings_numbered_from_0_are_milestones():
    plan = parse_milestones(SHORT_FORM)

    assert len(plan) == 3
    assert plan.context == "# A game\n\nRules for every milestone."
    assert [m.number for m in plan.milestones] == [1, 2, 3]
    assert plan.get(1).label == "M0 \u2014 Plan, Tech Stack Decision & Foundations"
    assert plan.get(3).label == "M2 \u2014 Player & Shooting"
    assert plan.get(2).text == "Build the loop."
    assert written_in_milestones(SHORT_FORM) == 3


@pytest.mark.parametrize(
    ("heading", "label"),
    [
        ("## Milestone 1 - Storage", "Storage"),
        ("## Milestone 1 \u2014 Storage", "Storage"),
        ("## Milestone 1. Storage", "Storage"),
        ("## milestone 1: Storage", "Storage"),
        ("## M1: Storage", "M1 \u2014 Storage"),
        ("## M1", "M1"),
    ],
)
def test_milestone_headings_can_be_written_in_several_ways(heading, label):
    plan = parse_milestones(f"{heading}\nDo it.\n## Milestone 2: b\nAnd this.")

    assert plan.get(1).label == label


def test_milestone_0_keeps_its_written_name():
    plan = parse_milestones("## Milestone 0: Plan\nx\n## Milestone 1: Build\ny")

    assert [m.label for m in plan.milestones] == [
        "Milestone 0 \u2014 Plan",
        "Milestone 1 \u2014 Build",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "## M16 rifle\nx\n## M17 rifle\ny",
        "## Mode 1: a\nx\n## Mode 2: b\ny",
        "## M2: a\nx\n## M3: b\ny",
        "## M0: a\nx\n## M2: b\ny",
    ],
)
def test_other_headings_are_not_milestones(text):
    assert written_in_milestones(text) == 0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Just a task.", "no milestone found"),
        ("## Milestone 1: a\nx\n## Milestone 3: b\ny", "numbered 1, 2, 3"),
        ("## Milestone 2: a\nx", "numbered 1, 2, 3"),
        ("## M1: a\nx\n```acceptance\nnot json\n```", "M1 \u2014 a: the acceptance block"),
        ("```acceptance\n[]\n```\n## Milestone 1: a\nx", "inside a milestone"),
        ("## Milestone 1: a\nx\n```acceptance\n[]\n```\n```acceptance\n[]\n```", "more than one"),
        ("## Milestone 1: a\nx\n```acceptance\nnot json\n```", "valid JSON"),
        ("## Milestone 1: a\nx\n```acceptance\n{}\n```", "JSON array"),
        ('## Milestone 1: a\nx\n```acceptance\n[{"kind": "run"}]\n```', "milestone 1:"),
        ("## Milestone 1: a\n```acceptance\n[]\n```", "has no text"),
        ("## Milestone 1: a\nx\n```acceptance\n[]", "isn't closed"),
    ],
)
def test_a_bad_task_file_is_refused(text, message):
    with pytest.raises(MilestoneError, match=message):
        parse_milestones(text)


def test_the_agent_gets_the_context_the_done_titles_and_this_milestone():
    plan = parse_milestones(TASK)

    first = milestone_task(plan, 1)
    second = milestone_task(plan, 2)

    assert first.startswith("# Todo app")
    assert "milestone 1 of 2: storage" in first
    assert "Do only this milestone" in first
    assert "Items can have a due date" not in first
    assert "Already done and checked" in second
    assert "1. storage" in second
    assert "Add and list items" not in second  # done milestones by title only
    assert "Do only this milestone" not in second  # the last one


def test_checks_add_up_milestone_by_milestone():
    plan = parse_milestones(
        "## Milestone 1: a\nx\n```acceptance\n"
        '[{"kind": "file_exists", "path": "a.py"}]\n```\n'
        "## Milestone 2: b\ny\n```acceptance\n"
        '[{"kind": "file_exists", "path": "b.py"}]\n```\n'
    )

    assert [c.path for c in checks_up_to(plan, 1)] == ["a.py"]
    assert [c.path for c in checks_up_to(plan, 2)] == ["a.py", "b.py"]


def _started(tmp_path, verdicts=None, current=None, text=TASK):
    """A plan started from a task file in `tmp_path`, saved in `tmp_path/project`."""
    task_file = tmp_path / "task.md"
    task_file.write_text(text)
    state = MilestoneState.from_text(text.strip(), str(task_file))
    state.verdicts.update(verdicts or {})
    state.current = current
    workspace = str(tmp_path / "project")
    ensure_state_dir(workspace)
    save_state(workspace, state)
    return workspace, task_file, state


def test_the_saved_plan_has_titles_and_verdicts_but_no_text_or_checks(tmp_path):
    workspace, _, _ = _started(tmp_path, {1: "verified"}, current=2)

    saved_text = (tmp_path / "project" / ".certo" / "milestones.json").read_text()
    saved = load_state(workspace)

    assert saved.titles == ("storage", "due dates")
    assert saved.verdicts == {1: "verified"}
    assert saved.current == 2
    assert saved.next_number() == 2
    assert "todo.py" not in saved_text  # the acceptance check
    assert "Add and list items" not in saved_text  # a milestone's text
    clear_state(workspace)
    assert load_state(workspace) is None


def test_reopen_reads_the_task_file_again(tmp_path):
    workspace, _, state = _started(tmp_path, {1: "verified"}, current=2)

    reopened = reopen(load_state(workspace))

    assert reopened == state
    assert reopened.plan.get(1).checks()[0].path == "todo.py"


def test_reopen_refuses_an_edited_task_file(tmp_path):
    workspace, task_file, _ = _started(tmp_path)
    task_file.write_text(TASK + "\nOne more line.\n")

    with pytest.raises(MilestoneError, match="changed since its milestones started"):
        reopen(load_state(workspace))


def test_reopen_refuses_a_missing_task_file(tmp_path):
    workspace, task_file, _ = _started(tmp_path)
    task_file.unlink()

    with pytest.raises(MilestoneError, match="can't read the task file"):
        reopen(load_state(workspace))


def test_next_number_is_none_when_every_milestone_is_verified(tmp_path):
    workspace, _, state = _started(tmp_path, {1: "verified", 2: "verified"})

    assert state.next_number() is None
    assert load_state(workspace).next_number() is None


def test_an_unreadable_plan_is_no_plan(tmp_path):
    ensure_state_dir(str(tmp_path))
    (tmp_path / ".certo" / "milestones.json").write_text("{not json")

    assert load_state(str(tmp_path)) is None
    assert status_lines(str(tmp_path)) == []


def test_status_md_lists_the_milestones(tmp_path):
    workspace, _, _ = _started(tmp_path, {1: "verified"}, current=2)
    record = RunRecord(
        task="the milestone's text",
        conversation_id="a" * 32,
        model="openai/gpt-4o",
        execution="local",
        started_at="2026-10-29T10:00:00+00:00",
        updated_at="2026-10-29T10:00:00+00:00",
    )

    save_record(workspace, record)

    status = open(status_path(workspace), encoding="utf-8").read()
    assert "## Milestones\n\n1. storage: `verified`\n2. due dates: this run\n" in status
    assert status.index("## Milestones") < status.index("## Task")


def test_summary_lines_say_which_were_not_started(tmp_path):
    _, _, state = _started(tmp_path, {1: "retry_exhausted"})

    assert summary_lines(state) == ["1. storage: retry_exhausted", "2. due dates: not started"]


# --- handover: what a milestone leaves for the next -------------------------


def _finish(text):
    return SimpleNamespace(role="tool", name="finish", content=[SimpleNamespace(text=text)])


def test_handover_lists_the_files_and_the_last_finish_summary(tmp_path):
    (tmp_path / "sheet.py").write_text("a = 1\nb = 2\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sheet.py").write_text("x")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0\0")
    (tmp_path / ".hidden").write_text("secret\n")
    (tmp_path / ".certo").mkdir()
    (tmp_path / ".certo" / "STATUS.md").write_text("x\n")
    messages = [_finish("Old summary."), SimpleNamespace(role="assistant"), _finish("Built it.")]

    text = handover(str(tmp_path), messages, 1)

    assert text.startswith("## What milestone 1 left")
    assert "- logo.png (6 bytes)\n- sheet.py (2 lines)\n- tests/test_sheet.py (1 line)" in text
    assert ".hidden" not in text and "STATUS.md" not in text
    assert "not checked by Certo" in text
    assert text.endswith("Built it.")
    assert "Old summary" not in text


def test_handover_is_none_with_nothing_to_say(tmp_path):
    assert handover(str(tmp_path), [], 1) is None


def test_handover_shortens_a_long_summary_and_a_long_file_list(tmp_path):
    for i in range(45):
        (tmp_path / f"f{i:02}.txt").write_text("")
    text = handover(str(tmp_path), [_finish("y" * 3000)], 2)

    assert "- f39.txt (0 lines)\n- ... and 5 more" in text
    assert "f40.txt" not in text
    assert text.endswith("y [...]")
    assert text.count("y") < 2100


def test_milestone_task_puts_the_handover_before_the_milestone():
    plan = parse_milestones(TASK)
    text = milestone_task(plan, 2, "## What milestone 1 left\n\n- todo.py (3 lines)")

    assert text.index("Already done and checked") < text.index("What milestone 1 left")
    assert text.index("What milestone 1 left") < text.index("## Now: milestone 2")


def test_a_milestone_task_is_recognised_whatever_its_handover():
    plan = parse_milestones(TASK)
    given = milestone_task(plan, 2, "## What milestone 1 left\n\n- todo.py (3 lines)\n\nDone.")

    assert is_milestone_task(given, plan, 2)
    assert is_milestone_task(milestone_task(plan, 2), plan, 2)
    assert not is_milestone_task(given, plan, 1)
    assert not is_milestone_task(given + " and more", plan, 2)


def test_handover_takes_the_last_plain_message_when_there_is_no_finish(tmp_path):
    def said(text, **extra):
        return SimpleNamespace(
            role="assistant", name=None, content=[SimpleNamespace(text=text)], **extra
        )

    messages = [
        said("Working.", tool_calls=[object()]),
        said("Converted both ways, with tests."),
        said(""),
        SimpleNamespace(role="assistant", name="certo", content=[SimpleNamespace(text="Notice")]),
    ]
    text = handover(str(tmp_path), messages, 1)

    assert text.endswith("Converted both ways, with tests.")
