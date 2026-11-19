"""The job runner, end to end: a real worker thread running real jobs."""

import threading

import pytest
from conftest import boom, work


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_jobs_run_in_the_order_submitted(runner, count):
    done = []
    ids = [runner.submit(lambda i=i: done.append(work(i))) for i in range(count)]
    runner.start()
    for job_id in ids:
        assert runner.wait(job_id)
    assert done == list(range(count))


@pytest.mark.parametrize("value", [0, 1, "text", [1, 2], {"a": 1}, None])
def test_a_job_s_result_is_what_it_returned(runner, value):
    job_id = runner.submit(work, value)
    runner.start()
    assert runner.wait(job_id)
    assert runner.status(job_id) == "done"
    assert runner.result(job_id) == value


@pytest.mark.parametrize("message", ["disk full", "timeout", "bad input"])
def test_a_job_that_raises_has_failed_with_its_exception(runner, message):
    job_id = runner.submit(boom, message)
    runner.start()
    assert runner.wait(job_id)
    assert runner.status(job_id) == "failed"
    assert str(runner.result(job_id)) == message


@pytest.mark.parametrize("count", [2, 3, 4])
def test_ids_go_up_from_one(runner, count):
    ids = [runner.submit(work, i) for i in range(count)]
    assert ids == list(range(1, count + 1))
    runner.start()
    for job_id in ids:
        assert runner.wait(job_id)


def test_jobs_wait_until_the_runner_starts(runner):
    job_id = runner.submit(work, 1)
    assert not runner.wait(job_id, timeout=0.5)
    assert runner.status(job_id) == "queued"
    runner.start()
    assert runner.wait(job_id)


def test_a_job_is_running_while_it_works(runner):
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return "ok"

    job_id = runner.submit(slow)
    runner.start()
    assert started.wait(5)
    assert runner.status(job_id) == "running"
    release.set()
    assert runner.wait(job_id)
    assert runner.result(job_id) == "ok"


@pytest.mark.parametrize("count", [2, 4, 6])
def test_a_failure_doesn_t_stop_the_jobs_after_it(runner, count):
    first = runner.submit(boom, "first")
    rest = [runner.submit(work, i) for i in range(count)]
    runner.start()
    assert runner.wait(first)
    for i, job_id in enumerate(rest):
        assert runner.wait(job_id)
        assert runner.result(job_id) == i


@pytest.mark.parametrize("count", [1, 3, 5])
def test_jobs_submitted_while_running_run_too(runner, count):
    runner.start()
    ids = [runner.submit(work, i) for i in range(count)]
    for i, job_id in enumerate(ids):
        assert runner.wait(job_id)
        assert runner.result(job_id) == i


def test_a_job_has_no_result_before_it_ends(runner):
    job_id = runner.submit(work, 5)
    assert runner.result(job_id) is None
    runner.start()
    assert runner.wait(job_id)
    assert runner.result(job_id) == 5


def test_an_unknown_id_is_a_key_error(runner):
    with pytest.raises(KeyError):
        runner.status(99)
    with pytest.raises(KeyError):
        runner.result(99)


def test_stop_lets_the_running_job_finish(runner):
    job_id = runner.submit(work, "last")
    runner.start()
    while runner.status(job_id) == "queued":
        pass
    runner.stop()
    assert runner.status(job_id) == "done"


@pytest.mark.parametrize("rounds", [1, 2, 3])
def test_the_runner_can_start_again_after_stop(runner, rounds):
    for r in range(rounds):
        job_id = runner.submit(work, r)
        runner.start()
        assert runner.wait(job_id)
        runner.stop()
        assert runner.result(job_id) == r
