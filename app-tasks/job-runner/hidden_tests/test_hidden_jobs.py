"""The job runner, every rule the task states, fast (no job sleeps).
Test names start with their milestone (m1_ to m3_); m1_starter_ is what the
starter already did and must keep doing."""

import threading

import pytest
from jobs import Runner


@pytest.fixture
def runner():
    r = Runner()
    yield r
    r.stop()


def run_all(runner, ids):
    runner.start()
    for job_id in ids:
        assert runner.wait(job_id, timeout=5)


def recorder():
    order = []

    def job(name):
        order.append(name)
        return name

    return order, job


# --- what the starter did (kept from milestone 1 on) -----------------------------


def test_m1_starter_jobs_run_in_the_order_submitted(runner):
    order, job = recorder()
    run_all(runner, [runner.submit(job, n) for n in "abcd"])
    assert order == list("abcd")


def test_m1_starter_results_failures_and_ids(runner):
    def fail():
        raise RuntimeError("no")

    ok, bad = runner.submit(lambda: 42), runner.submit(fail)
    assert (ok, bad) == (1, 2)
    run_all(runner, [ok, bad])
    assert (runner.status(ok), runner.result(ok)) == ("done", 42)
    assert runner.status(bad) == "failed"
    assert str(runner.result(bad)) == "no"
    with pytest.raises(KeyError):
        runner.status(99)


# --- milestone 1: priorities ----------------------------------------------------------


def test_m1_the_highest_priority_runs_first(runner):
    order, job = recorder()
    ids = [
        runner.submit(job, "low", priority=-1),
        runner.submit(job, "mid"),
        runner.submit(job, "high", priority=5),
        runner.submit(job, "mid2", priority=0),
        runner.submit(job, "high2", priority=5),
    ]
    run_all(runner, ids)
    assert order == ["high", "high2", "mid", "mid2", "low"]


def test_m1_queued_lists_the_ids_in_running_order(runner):
    a = runner.submit(lambda: 1)
    b = runner.submit(lambda: 2, priority=3)
    c = runner.submit(lambda: 3, priority=3)
    d = runner.submit(lambda: 4, priority=-2)
    assert runner.queued() == [b, c, a, d]
    run_all(runner, [a, b, c, d])
    assert runner.queued() == []


@pytest.mark.parametrize("bad", [True, 1.5, "1", None])
def test_m1_a_priority_that_isn_t_an_int_is_refused_and_uses_no_id(runner, bad):
    with pytest.raises(TypeError):
        runner.submit(lambda: 1, priority=bad)
    assert runner.queued() == []
    assert runner.submit(lambda: 1) == 1


def test_m1_priority_is_given_by_keyword_and_args_still_reach_the_job(runner):
    job_id = runner.submit(lambda x, y: x + y, 2, 3, priority=1)
    run_all(runner, [job_id])
    assert runner.result(job_id) == 5


def test_m1_a_job_submitted_later_with_a_higher_priority_goes_first(runner):
    order, job = recorder()
    gate = threading.Event()
    first = runner.submit(lambda: gate.wait(5))
    runner.start()
    while runner.status(first) == "queued":
        pass
    later = [runner.submit(job, "a"), runner.submit(job, "b", priority=9)]
    gate.set()
    for job_id in [first, *later]:
        assert runner.wait(job_id, timeout=5)
    assert order == ["b", "a"]


# --- milestone 2: retries -------------------------------------------------------------


def flaky(failures):
    """A job that raises on its first `failures` runs."""
    calls = {"n": 0}

    def job():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise RuntimeError(f"run {calls['n']}")
        return "ok"

    return job, calls


def test_m2_a_job_is_run_again_until_it_works(runner):
    job, calls = flaky(2)
    job_id = runner.submit(job, retries=3)
    run_all(runner, [job_id])
    assert (runner.status(job_id), runner.result(job_id)) == ("done", "ok")
    assert calls["n"] == 3
    assert runner.attempts(job_id) == 3


def test_m2_after_the_last_retry_it_fails_with_the_last_exception(runner):
    job, calls = flaky(10)
    job_id = runner.submit(job, retries=2)
    run_all(runner, [job_id])
    assert runner.status(job_id) == "failed"
    assert str(runner.result(job_id)) == "run 3"
    assert calls["n"] == 3
    assert runner.attempts(job_id) == 3


def test_m2_no_retries_by_default(runner):
    job, calls = flaky(1)
    job_id = runner.submit(job)
    run_all(runner, [job_id])
    assert runner.status(job_id) == "failed"
    assert calls["n"] == 1
    assert runner.attempts(job_id) == 1


def test_m2_a_retry_runs_before_any_other_job(runner):
    order = []
    calls = {"n": 0}

    def flaky_job():
        calls["n"] += 1
        order.append(f"flaky{calls['n']}")
        if calls["n"] < 3:
            raise RuntimeError("again")

    ids = [
        runner.submit(flaky_job, retries=5, priority=1),
        runner.submit(lambda: order.append("other"), priority=1),
    ]
    run_all(runner, ids)
    assert order == ["flaky1", "flaky2", "flaky3", "other"]


def test_m2_attempts_is_zero_while_queued(runner):
    job_id = runner.submit(lambda: 1, retries=1)
    assert runner.attempts(job_id) == 0
    with pytest.raises(KeyError):
        runner.attempts(99)


@pytest.mark.parametrize("bad", [-1, 1.5, "2", None])
def test_m2_bad_retries_are_refused_and_use_no_id(runner, bad):
    with pytest.raises(ValueError):
        runner.submit(lambda: 1, retries=bad)
    assert runner.submit(lambda: 1) == 1


# --- milestone 3: cancelling ----------------------------------------------------------


def test_m3_a_queued_job_is_cancelled_and_never_runs(runner):
    order, job = recorder()
    a, b, c = (runner.submit(job, n) for n in "abc")
    assert runner.cancel(b) is True
    assert runner.status(b) == "cancelled"
    assert runner.queued() == [a, c]
    run_all(runner, [a, c])
    assert order == ["a", "c"]
    assert runner.status(b) == "cancelled"
    assert runner.result(b) is None


def test_m3_waiting_on_a_cancelled_job_returns_at_once(runner):
    job_id = runner.submit(lambda: 1)
    runner.cancel(job_id)
    assert runner.wait(job_id, timeout=0.5) is True


def test_m3_a_running_or_ended_job_can_t_be_cancelled(runner):
    gate = threading.Event()
    running = runner.submit(lambda: gate.wait(5) and "late")
    runner.start()
    while runner.status(running) == "queued":
        pass
    assert runner.cancel(running) is False
    gate.set()
    assert runner.wait(running, timeout=5)
    assert runner.status(running) == "done"
    assert runner.cancel(running) is False
    assert runner.status(running) == "done"


def test_m3_cancel_twice_and_unknown_ids(runner):
    job_id = runner.submit(lambda: 1)
    assert runner.cancel(job_id) is True
    assert runner.cancel(job_id) is False
    with pytest.raises(KeyError):
        runner.cancel(99)
