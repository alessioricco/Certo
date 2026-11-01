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
