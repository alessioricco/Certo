"""Tests for certo.agent. No network: build_agent() only constructs SDK
objects, it never calls the LLM.
"""

from __future__ import annotations

import os

from certo.agent import (
    _AUTONOMOUS_SUFFIX,
    _CERTO_STATE_SUFFIX,
    _LIFECYCLE_SKILLS_SUFFIX,
    _NONINTERACTIVE_TOOLING_SUFFIX,
    _README_SUFFIX,
    _VERIFY_BEFORE_FINISH_SUFFIX,
    build_agent,
)
from certo.config import Config


def _cfg(**overrides) -> Config:
    base = dict(
        model="openai/gpt-4o",
        api_key="key",
        base_url=None,
        workspace=".",
        max_iterations=10,
        confirm_mode="never",
        execution="local",
    )
    base.update(overrides)
    return Config(**base)


def test_agent_context_carries_all_system_message_suffix_policies():
    agent = build_agent(_cfg())

    assert agent.agent_context is not None
    suffix = agent.agent_context.system_message_suffix
    assert _AUTONOMOUS_SUFFIX in suffix
    assert _README_SUFFIX in suffix
    assert _NONINTERACTIVE_TOOLING_SUFFIX in suffix
    assert _CERTO_STATE_SUFFIX in suffix
    assert _VERIFY_BEFORE_FINISH_SUFFIX in suffix
    assert _LIFECYCLE_SKILLS_SUFFIX in suffix


def test_autonomous_suffix_tells_agent_not_to_wait_for_the_user():
    # Regression guard for failure mode #1: the SDK treats a plain-text reply
    # (e.g. a clarifying question) exactly like a `finish` tool call and
    # silently ends the run — see agent.py's comment on _AUTONOMOUS_SUFFIX.
    # Loosely assert the instruction actually tells the agent to keep working
    # instead of waiting.
    assert "finish" in _AUTONOMOUS_SUFFIX
    assert "ask" in _AUTONOMOUS_SUFFIX.lower() or "wait" in _AUTONOMOUS_SUFFIX.lower()


def test_autonomous_suffix_forbids_declaring_early_completion():
    # Regression guard for failure mode #2: after fixing #1 live, the agent
    # stopped asking questions but instead built 1 of 6 task_tracker items
    # and declared success, framing the rest as "next steps for you" — see
    # agent.py's comment on _AUTONOMOUS_SUFFIX. Loosely assert the
    # instruction tells the agent to keep going instead of handing back
    # unfinished work.
    lowered = _AUTONOMOUS_SUFFIX.lower()
    assert "task_tracker" in lowered
    assert "next step" in lowered


def test_readme_suffix_requires_concrete_run_instructions():
    lowered = _README_SUFFIX.lower()
    assert "readme" in lowered
    assert "run" in lowered
    assert "install" in lowered


def test_noninteractive_suffix_tells_agent_to_use_ci_flags_and_not_retry_blindly():
    # Regression guard for failure mode #3: asked to scaffold with Vite, the
    # agent ran `npm create vite@latest ... -- --template react-ts`, which
    # started an interactive prompt that auto-cancelled with no TTY/human to
    # answer it (exit code 0, nothing created) — then just re-ran the
    # identical command instead of noticing nothing happened or using the
    # non-interactive flag the tool's own output suggested. See agent.py's
    # comment on _NONINTERACTIVE_TOOLING_SUFFIX.
    lowered = _NONINTERACTIVE_TOOLING_SUFFIX.lower()
    assert "non-interactive" in lowered
    assert "retry" in lowered or "identical" in lowered


def test_verify_before_finish_suffix_requires_running_before_claiming_done():
    # Regression guard for failure mode #4: asked to build a Tower of Hanoi
    # game, the agent explicitly called `finish` admitting "there are errors
    # in the tests that need further debugging" — a deliberate finish call
    # despite known failure, not an accidental plain-text stop. Its own
    # diagnosis was also wrong: the file had an IndentationError and didn't
    # even parse, so every test failed at collection, not from "sequence
    # handling" as claimed — it never re-ran anything before writing that
    # summary. See agent.py's comment on _VERIFY_BEFORE_FINISH_SUFFIX.
    lowered = _VERIFY_BEFORE_FINISH_SUFFIX.lower()
    assert "finish" in lowered
    assert "run" in lowered
    assert "verify" in lowered


def test_lifecycle_skills_suffix_names_repository_discovery_explicitly():
    # repository-discovery is the one skill this suffix names directly (it
    # has no single obvious trigger word the way the others do) — a
    # typo'd/paraphrased name here would be silently useless.
    assert "`repository-discovery`" in _LIFECYCLE_SKILLS_SUFFIX


def test_lifecycle_skills_suffix_tells_agent_to_inspect_before_editing():
    lowered = _LIFECYCLE_SKILLS_SUFFIX.lower()
    assert "before editing" in lowered
    assert "inspect" in lowered


def test_lifecycle_skills_suffix_allows_skipping_trivial_tasks():
    lowered = _LIFECYCLE_SKILLS_SUFFIX.lower()
    assert "skip" in lowered
    assert "one-line fix" in lowered or "too small" in lowered


def test_lifecycle_skills_suffix_says_skills_are_not_a_substitute_for_verification():
    lowered = _LIFECYCLE_SKILLS_SUFFIX.lower()
    assert "not a substitute" in lowered or "never a substitute" in lowered
    assert "verify" in lowered or "run the checks" in lowered


def test_agent_context_still_loads_project_skills():
    agent = build_agent(_cfg())

    assert agent.agent_context is not None
    assert agent.agent_context.load_project_skills is True


# --- CERTO_INTERACTIVE=yes: drops _AUTONOMOUS_SUFFIX, keeps the rest -----


def test_autonomous_suffix_present_by_default():
    agent = build_agent(_cfg())

    assert _AUTONOMOUS_SUFFIX in agent.agent_context.system_message_suffix


def test_interactive_mode_drops_the_autonomous_suffix():
    agent = build_agent(_cfg(interactive=True))

    assert _AUTONOMOUS_SUFFIX not in agent.agent_context.system_message_suffix


def test_interactive_mode_keeps_every_other_suffix():
    agent = build_agent(_cfg(interactive=True))

    suffix = agent.agent_context.system_message_suffix
    assert _README_SUFFIX in suffix
    assert _NONINTERACTIVE_TOOLING_SUFFIX in suffix
    assert _CERTO_STATE_SUFFIX in suffix
    assert _VERIFY_BEFORE_FINISH_SUFFIX in suffix
    assert _LIFECYCLE_SKILLS_SUFFIX in suffix


def test_certo_state_suffix_protects_dot_certo_from_scaffolders():
    # create-vite 9.3.0 in a folder holding .certo/: "Operation cancelled"
    # with exit 0, and --overwrite deletes .certo/. The agent must keep it
    # and scaffold into a subfolder instead.
    text = _CERTO_STATE_SUFFIX
    assert "never delete" in text
    assert "--overwrite" in text
    assert "subfolder" in text
    assert "hidden" in text


# --- usage_id passthrough (auto model selection) ----------------------------


def test_build_agent_usage_id_defaults_to_certo():
    agent = build_agent(_cfg())

    assert agent.llm.usage_id == "certo"


def test_build_agent_usage_id_is_overridable():
    agent = build_agent(_cfg(), usage_id="certo:deep-reasoner")

    assert agent.llm.usage_id == "certo:deep-reasoner"


def _project_env():
    from certo.project_env import ProjectEnv

    return ProjectEnv(
        kind="venv",
        host_dir="/p/.venv",
        venv_dir="/p/.venv",
        python=("/p/.venv/bin/python",),
        install_hint="python -m pip install <package>",
    )


def test_project_env_policy_line_only_when_the_project_has_one():
    with_env = build_agent(_cfg(), project_env=_project_env())
    without = build_agent(_cfg())

    suffix = with_env.agent_context.system_message_suffix
    assert "own Python environment at /p/.venv" in suffix
    assert "python -m pip install <package>" in suffix
    assert "own Python environment" not in without.agent_context.system_message_suffix


def test_readme_suffix_mentions_the_project_environment():
    assert "virtual environment" in _README_SUFFIX


def test_terminal_env_reaches_the_terminal_tool_spec_with_the_subprocess_backend():
    env = {"VIRTUAL_ENV": "/p/.venv", "PATH": "/p/.venv/bin:/usr/bin"}

    agent = build_agent(_cfg(), terminal_env=env)

    terminal = next(t for t in agent.tools if t.name == "terminal")
    assert terminal.params == {"env": env, "terminal_type": "subprocess"}


def test_terminal_tool_spec_is_untouched_without_a_terminal_env():
    agent = build_agent(_cfg())

    terminal = next(t for t in agent.tools if t.name == "terminal")
    assert terminal.params == {}


def test_the_condenser_summarizes_only_near_the_context_window():
    from openhands.sdk.context.condenser import LLMSummarizingCondenser

    agent = build_agent(_cfg())

    assert isinstance(agent.condenser, LLMSummarizingCondenser)
    assert agent.condenser.llm.model == agent.llm.model
    assert agent.condenser.max_size == 1_000_000  # no event-count trigger
    assert agent.condenser.keep_first == 4


def test_the_condenser_can_be_turned_off():
    assert build_agent(_cfg(condense=False)).condenser is None


def test_the_agent_is_told_its_project_root(tmp_path):
    suffix = build_agent(_cfg(workspace=str(tmp_path))).agent_context.system_message_suffix

    assert f"The project root is {tmp_path}. Work only inside it" in suffix
    assert "Never read, list or search anything above or outside it" in suffix


def test_in_docker_the_root_is_the_containers_folder():
    from certo.agent import project_root

    assert project_root(_cfg(execution="docker", workspace="/home/me/app")) == "/workspace"
    assert project_root(_cfg(workspace=".")) == os.path.abspath(".")
