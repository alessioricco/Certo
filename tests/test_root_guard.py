"""The root guard (root_guard.py): real SDK action classes, no model."""

from __future__ import annotations

import os
import sys

import pytest
from openhands.sdk.event import ActionEvent, ObservationEvent
from openhands.sdk.llm import MessageToolCall
from openhands.tools.file_editor import FileEditorAction
from openhands.tools.terminal import TerminalAction

from certo.custom_tools.run_tests_tool import RunTestsAction
from certo.root_guard import RootGuard

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths")


@pytest.fixture
def layout(tmp_path):
    """workspace/projects/app (the root) next to workspace/projects/other."""
    root = tmp_path / "workspace" / "projects" / "app"
    (root / "src").mkdir(parents=True)
    (tmp_path / "workspace" / "projects" / "other").mkdir()
    return root


def _guard(root):
    return RootGuard(str(root))


def _run(command):
    return TerminalAction(command=command)


@posix_only
@pytest.mark.parametrize(
    "command",
    [
        "ls ..",
        "ls -la ../",
        "cat ../other/package.json",
        "grep -rn foo ../..",
        "find / -name '*.md'",
        "cd ~",
        "cd",
        "cd; ls",
        "ls ~/Documents",
        "cat $HOME/.ssh/id_rsa",
        "cat ${HOME}/.config/certo/.env",
        "ls src/../../other",
        "git -C .. status",
        "npm install --prefix=../other",
    ],
)
def test_commands_that_reach_outside_are_blocked(layout, command):
    reason = _guard(layout).check(_run(command))

    assert reason is not None
    assert "is outside the project root" in reason


@posix_only
@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "ls -la src",
        "cat src/../README.md",
        "npm test 2>/dev/null",
        "python -c 'import os; print(os.listdir(\"../..\"))'",  # code, not a path
        "grep -rE '/api/v1' src",  # not a path
        "curl http://127.0.0.1:5173/api",
        "ls /tmp && ls /usr/bin",
        "ls ~/.npm ~/.cache/ms-playwright",
        f"ls {os.path.join('.', 'src')}",
        "PATH=/usr/local/bin:$PATH npm run build",
    ],
)
def test_commands_inside_the_root_run(layout, command):
    assert _guard(layout).check(_run(command)) is None


@posix_only
def test_dot_dot_counts_from_the_terminals_current_folder(layout):
    guard = _guard(layout)
    guard.cwd = str(layout / "src")

    assert guard.check(_run("cat ../package.json")) is None
    assert guard.check(_run("cat ../../other/x")) is not None


def test_input_to_a_running_program_is_never_read_as_a_path(layout):
    assert _guard(layout).check(TerminalAction(command="/quit", is_input=True)) is None


def test_the_file_editor_stays_in_the_root(layout):
    guard = _guard(layout)
    inside = FileEditorAction(command="create", path=str(layout / "src" / "a.py"), file_text="")
    outside = FileEditorAction(command="view", path=str(layout.parent / "other"))

    assert guard.check(inside) is None
    assert "is outside the project root" in guard.check(outside)


@posix_only
def test_the_file_editor_may_read_but_never_write_system_folders(layout):
    guard = _guard(layout)

    assert guard.check(FileEditorAction(command="view", path="/usr/include")) is None
    assert (
        guard.check(FileEditorAction(command="create", path="/tmp/x.py", file_text="")) is not None
    )


def test_run_tests_with_a_path_outside_is_blocked(layout):
    guard = _guard(layout)

    assert guard.check(RunTestsAction(path="tests/test_a.py")) is None
    assert guard.check(RunTestsAction(path="")) is None
    assert guard.check(RunTestsAction(path="../other")) is not None


# --- as a conversation callback -----------------------------------------------


class _State:
    def __init__(self):
        self.blocked = {}

    def block_action(self, action_id, reason):
        self.blocked[action_id] = reason


class _Conversation:
    def __init__(self):
        self.state = _State()


def _event(action):
    call = MessageToolCall(id="c1", name="terminal", arguments="{}", origin="completion")
    return ActionEvent(
        source="agent",
        thought=[],
        action=action,
        tool_name="terminal",
        tool_call_id="c1",
        tool_call=call,
        llm_response_id="r1",
    )


def test_a_blocked_action_is_marked_in_the_conversation_and_said(layout):
    said = []
    guard = RootGuard(str(layout), emit=said.append)
    guard.conversation = _Conversation()
    allowed, blocked = _event(_run("ls")), _event(_run("ls ../other"))

    guard(allowed)
    guard(blocked)

    assert list(guard.conversation.state.blocked) == [blocked.id]
    assert len(guard.blocked) == 1
    assert said[0].startswith("Certo blocked an action outside the project root: ")


def test_the_terminals_folder_follows_its_observations(layout):
    from openhands.tools.terminal import TerminalObservation
    from openhands.tools.terminal.metadata import CmdOutputMetadata

    guard = _guard(layout)
    observation = TerminalObservation.from_text(
        text="", command="cd src", metadata=CmdOutputMetadata(working_dir=str(layout / "src"))
    )
    guard(
        ObservationEvent(
            source="environment",
            observation=observation,
            action_id="a1",
            tool_name="terminal",
            tool_call_id="c1",
        )
    )

    assert guard.cwd == os.path.realpath(layout / "src")
