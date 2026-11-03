"""result.py: a run's JSON result. No LLM: outcomes are constructed."""

from __future__ import annotations

import json

from certo.acceptance import AcceptanceCheck, AcceptanceCheckResult
from certo.result import OUTPUT_TAIL_CHARS, RESULT_VERSION, run_result
from certo.run_summary import ModelUsage, RunSummary
from certo.runner import CompletionContract, TaskOutcome
from certo.verification import CheckOutcome


def _outcome(**overrides) -> TaskOutcome:
    base = {
        "verification_state": "retry_exhausted",
        "completion_contract": CompletionContract(
            goal="", acceptance_criteria=[], verification_checks=[], limitations=["pytest failed"]
        ),
        "checks": (
            CheckOutcome(
                name="pytest",
                command="python -m pytest",
                primary=True,
                status="failed",
                exit_code=1,
                project_root="/p",
                summary="1 failed",
                output="x" * (OUTPUT_TAIL_CHARS + 10) + "FAILED test_a",
            ),
        ),
        "retries_used": 2,
        "tool_call_reminders": 3,
        "acceptance_results": (
            AcceptanceCheckResult(AcceptanceCheck(kind="file_exists", path="a.py"), True, "found"),
        ),
        "run_summary": RunSummary(
            duration_seconds=12.34,
            models=(ModelUsage("anthropic/claude-haiku-5-5", 100, 20, 50, 0, 0.0123),),
        ),
    }
    base.update(overrides)
    return TaskOutcome(**base)


def test_a_finished_run_gives_its_verdict_checks_and_usage():
    result = run_result(_outcome(), task="do it", workspace="/p", project="demo")
    assert result["result_version"] == RESULT_VERSION
    assert result["verdict"] == "retry_exhausted"
    assert result["limitations"] == ["pytest failed"]
    check = result["checks"][0]
    assert (check["name"], check["status"], check["exit_code"]) == ("pytest", "failed", 1)
    assert len(check["output_tail"]) == OUTPUT_TAIL_CHARS
    assert check["output_tail"].endswith("FAILED test_a")
    assert result["acceptance"] == [
        {
            "kind": "file_exists",
            "path": "a.py",
            "contains": None,
            "required": True,
            "description": None,
            "passed": True,
            "detail": "found",
        }
    ]
    assert result["retries_used"] == 2
    assert result["tool_call_reminders"] == 3
    assert result["usage"]["duration_seconds"] == 12.3
    assert result["usage"]["total_tokens"] == 120
    assert result["usage"]["cost"] == 0.0123
    assert result["usage"]["models"][0]["model"] == "anthropic/claude-haiku-5-5"
    json.dumps(result)


def test_a_run_that_stopped_has_no_verdict_and_says_why():
    result = run_result(None, task="do it", workspace="/p", error="interrupted")
    assert result["verdict"] is None
    assert result["error"] == "interrupted"
    assert result["checks"] == []
    assert result["usage"] is None


def test_milestones_are_listed_with_their_verdicts():
    milestones = [{"number": 1, "title": "a", "verdict": "verified"}]
    result = run_result(_outcome(), task="t", workspace="/p", milestones=milestones)
    assert result["milestones"] == milestones


def test_the_files_a_run_changed_are_listed():
    from certo.escalation import FileChanges

    changes = FileChanges(created=("a.py",), modified=("README.md",), deleted=("old.py",))
    result = run_result(_outcome(files_changed=changes), task="t", workspace="/p")
    assert result["files_changed"] == {
        "created": ["a.py"],
        "modified": ["README.md"],
        "deleted": ["old.py"],
    }
    assert run_result(None, task="t", workspace="/p")["files_changed"] is None


def test_independent_tests_show_their_sets_and_output():
    from certo.independent_tests import IndependentTestsResult

    sets = (
        IndependentTestsResult("passed", "4 passed", "m"),
        IndependentTestsResult("failed", "1 failed", "m"),
    )
    found = IndependentTestsResult("split", "1 of 2 sets failed", "m", output="FAILED x", sets=sets)
    result = run_result(_outcome(independent_tests=found), task="t", workspace="/p")
    assert result["independent_tests"] == {
        "status": "split",
        "summary": "1 of 2 sets failed",
        "model": "m",
        "output_tail": "FAILED x",
        "sets": [
            {"status": "passed", "summary": "4 passed"},
            {"status": "failed", "summary": "1 failed"},
        ],
    }


def test_model_decisions_say_how_each_model_was_chosen():
    from certo.model_selection import ModelDecisionRecord

    decision = ModelDecisionRecord(
        kind="initial",
        timestamp="2026-11-01T10:00:00+00:00",
        task_profile="web",
        weights={"precision": 2.0},
        ranked=(("haiku", 8.0), ("sonnet", 6.5)),
        chosen="haiku",
        reason="highest score",
    )
    result = run_result(_outcome(model_decisions=(decision,)), task="t", workspace="/p")
    assert result["model_decisions"] == [
        {
            "kind": "initial",
            "timestamp": "2026-11-01T10:00:00+00:00",
            "task_profile": "web",
            "weights": {"precision": 2.0},
            "scored_by": "score",
            "candidates": [{"name": "haiku", "score": 8.0}, {"name": "sonnet", "score": 6.5}],
            "chosen": "haiku",
            "reason": "highest score",
        }
    ]
    assert run_result(_outcome(), task="t", workspace="/p")["model_decisions"] is None
    json.dumps(result)
