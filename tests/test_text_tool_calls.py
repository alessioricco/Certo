"""Tool calls written as text: the shapes come from saved benchmark
transcripts (qwen3.8, qwen3.6, devstral), with shorter paths."""

import pytest

from certo.text_tool_calls import DEFAULT_TOOLS, announces_next_step, looks_like_tool_call

TOOLS = {
    "terminal": ["command", "is_input", "reset", "timeout"],
    "file_editor": [
        "command",
        "file_text",
        "insert_line",
        "new_str",
        "old_str",
        "path",
        "view_range",
    ],
    "task_tracker": ["command", "task_list"],
}


@pytest.mark.parametrize(
    "text",
    [
        '{"command": "view", "path": "/tmp/certo-bench-r7rz1uvo"}',
        '{"command": "view", "path": "/tmp/p", "summary": "Explore project directory structure"}',
        '{"command": "find /tmp/p -type f | head -50", "is_input": false, '
        '"security_risk": "LOW", "summary": "Explore repository structure"}',
        '{"tool_name": "terminal", "arguments": {"command": "cat -n tests/test_money.py"}}',
        '{"name": "file_editor", "arguments": {"command": "view", "path": "/tmp/p"}}',
        '{"tool": "file_editor", "arguments": {"command": "view", "path": "/tmp/p"}}',
        '{"tool_use": "file_editor", "arguments": {"path": "package.json", "command": "view"}}',
        '{"name": "file_editor", "command": "view", "path": "/tmp/p"}',
        '{"name": "task_tracker", "command": "plan", "task_list": []}',
        '{"type": "function", "function": {"name": "terminal", "arguments": {"command": "ls"}}}',
        '{"id": "call_8a7f", "type": "function", "function": {"name": "file_editor", '
        '"command": "create", "path": "t.py", "file_text": "import pytest"}}',
        '{"task_tracker": {"task_list": [{"title": "Write tests", "status": "todo"}]}}',
        '{"tool_use": {"name": "file_editor", "arguments": {"command": "view"}}}',
        '{"command": "file_editor", "arguments": {"command": "view", "path": "/tmp/p", '
        '"security_risk": "LOW", "summary": "View project directory structure"}}',
        '{"type": "tool_result", "tool_use_id": "call_1", "content": "Let me continue '
        'viewing the rest of the test file and then plan the implementation."}',
        '{"type": "tool_use", "tool_use_id": "call_2", "content": "Let me continue."}',
        '```json\n{"command": "view", "path": "/tmp/p"}\n```',
        '<tool_call>\n{"name": "terminal", "arguments": {"command": "ls"}}\n</tool_call>',
    ],
)
def test_a_tool_call_written_as_text_is_recognised(text):
    assert looks_like_tool_call(text, TOOLS)


def test_a_call_cut_off_mid_file_is_recognised():
    cut = (
        '{"name": "file_editor", "arguments": {"command": "create", "file_text": "use std::env;\\n'
    )
    assert looks_like_tool_call(cut, TOOLS)
    assert looks_like_tool_call(
        '{"command": "create", "path": "src/main.rs", "file_text": "fn', TOOLS
    )


@pytest.mark.parametrize(
    "text",
    [
        "Done. All 33 tests pass.",
        'I ran `{"command": "view"}` and it worked.',
        '{"thinking": "Let me trace through each failing test."}',
        '{"reasoning": "Review the regex.", "thought": "It handles v."}',
        '{"name": "Ada", "arguments": {"x": 1}}',
        '{"command": "read_file", "path": "a.js", "start_line": 1, "end_line": 9}',
        '{"summary": "only the framework field"}',
        '{"type": "text", "text": "Done. All tests pass."}',
        '{"command": "ls -la", "arguments": {"x": 1}}',
        "{}",
        "[1, 2, 3]",
        "{not json and no known key",
    ],
)
def test_prose_and_other_json_are_not_tool_calls(text):
    assert not looks_like_tool_call(text, TOOLS)


def test_without_the_tools_the_built_in_ones_are_assumed():
    assert looks_like_tool_call('{"command": "view", "path": "/tmp"}')
    assert looks_like_tool_call('{"tool_name": "terminal", "arguments": {"command": "ls"}}')
    assert not looks_like_tool_call('{"command": "ls", "query": "x"}')
    assert not looks_like_tool_call('{"tool_name": "search", "arguments": {}}')


def test_the_default_tools_match_the_sdk():
    from openhands.tools.file_editor import FileEditorAction
    from openhands.tools.task_tracker import TaskTrackerAction
    from openhands.tools.terminal import TerminalAction

    assert DEFAULT_TOOLS == {
        "terminal": set(TerminalAction.model_fields),
        "file_editor": set(FileEditorAction.model_fields),
        "task_tracker": set(TaskTrackerAction.model_fields),
    }


# The four endings of saved local runs that announced a next step and stopped.
@pytest.mark.parametrize(
    "text",
    [
        '{"type": "text", "text": "Now let me look at the test file to understand '
        'conventions, then implement milestone 3."}',
        '{"type": "text", "text": "Good, imports are in place. Now let me add the `save` '
        'and `load` methods to the `Ledger` class."}',
        '{"message": "I\'ve created `durations.py`. Let me now run the tests to verify '
        'everything works.", "tool_use_id": "call_abc123", "arguments": {"command": '
        '"python -m pytest test_durations.py -v", "timeout": 30}}',
        '{"thinking": "Let me trace through each failing test.\\n\\nAll 5 failures are '
        'test bugs. Let me fix them."}',
        "The parser is in place. Next, I'll add the tests.",
    ],
)
def test_a_message_that_announces_its_next_step_is_recognised(text):
    assert announces_next_step(text)


@pytest.mark.parametrize(
    "text",
    [
        "Done, all tests pass.",
        "I added `save` and `load`. Let me know if you want a CSV export too.",
        "Now let me check the tests. All 12 pass, so the ledger is complete.",
        '{"type": "text", "text": "The ledger is complete and its tests pass."}',
        '{"command": "view", "path": "/tmp/project"}',
        '{"type": "text", "text": "Now let me',
        "",
    ],
)
def test_a_finished_answer_does_not_announce_a_next_step(text):
    assert not announces_next_step(text)
