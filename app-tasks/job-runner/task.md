# Job runner

This folder holds a small job runner in Python, `jobs.py`, and its tests
in `tests/`. Jobs wait in a queue and run one at a time on a worker
thread. Add three features, one milestone each, using only the standard
library. Keep everything that works today working, keep the existing
tests passing, and add pytest tests in `tests/` for what you add.

## Milestone 1: priorities

- `runner.submit(fn, *args, priority=0)`: `priority` is a whole number,
  given by keyword. When the worker takes its next job, it takes the
  queued job with the highest priority; of jobs with the same priority,
  the one submitted first. A priority that isn't an `int` (`True` and
  `1.5` aren't) raises `TypeError`; then nothing is queued and no id is
  used.
- `runner.queued()` returns the ids of the jobs still queued, as a list
  in the order they will run.
```acceptance
[{"kind": "file_contains", "path": "jobs.py", "contains": "def queued"}]
```

## Milestone 2: retries

- `runner.submit(fn, *args, priority=0, retries=0)`: a job that raises
  is run again, at once, before any other job, up to `retries` more
  times. If one of its runs returns, the job is `done` with that result.
  If every run raises, the job is `failed`, and its result is the
  exception of the last run. `retries` that isn't an `int`, or is below
  zero, raises `ValueError`; then nothing is queued and no id is used.
- `runner.attempts(job_id)` returns how many times the job has started:
  `0` while it is queued. An id the runner doesn't know raises
  `KeyError`.
```acceptance
[{"kind": "file_contains", "path": "jobs.py", "contains": "def attempts"}]
```

## Milestone 3: cancelling

- `runner.cancel(job_id)`: a job that is still queued gets the status
  `"cancelled"`, never runs, and `cancel` returns `True`. A job that is
  running or has ended doesn't change, and `cancel` returns `False`. An
  id the runner doesn't know raises `KeyError`.
- A cancelled job has ended: `runner.wait(job_id)` returns `True` at
  once, its result is `None`, and `runner.queued()` leaves it out.
```acceptance
[{"kind": "file_contains", "path": "jobs.py", "contains": "def cancel"}]
```
