"""A small job runner: jobs wait in a queue and run one at a time, in the
order they were submitted, on one worker thread."""

from __future__ import annotations

import itertools
import threading


class Runner:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._queue: list[int] = []
        self._jobs: dict[int, dict] = {}
        self._lock = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopping = False

    def submit(self, fn, *args) -> int:
        """Queue `fn(*args)` and return the job's id: 1, 2, 3..."""
        with self._lock:
            job_id = next(self._ids)
            self._jobs[job_id] = {"fn": fn, "args": args, "status": "queued", "result": None}
            self._queue.append(job_id)
            self._lock.notify_all()
            return job_id

    def status(self, job_id: int) -> str:
        """ "queued", "running", "done" or "failed". KeyError for an unknown id."""
        with self._lock:
            return self._jobs[job_id]["status"]

    def result(self, job_id: int):
        """What the job returned (done) or the exception it raised (failed);
        None before it ends."""
        with self._lock:
            return self._jobs[job_id]["result"]

    def wait(self, job_id: int, timeout: float = 10.0) -> bool:
        """Wait until the job has ended; False if it hasn't after `timeout` seconds."""
        with self._lock:
            return self._lock.wait_for(
                lambda: self._jobs[job_id]["status"] in ("done", "failed"), timeout
            )

    def start(self) -> None:
        """Start the worker thread. Jobs submitted before start wait for it."""
        with self._lock:
            if self._thread is not None:
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._work, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Let the running job finish, then end the worker thread."""
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join()
        with self._lock:
            self._thread = None

    def _next(self) -> int | None:
        with self._lock:
            self._lock.wait_for(lambda: self._queue or self._stopping)
            if self._stopping:
                return None
            job_id = self._queue.pop(0)
            self._jobs[job_id]["status"] = "running"
            return job_id

    def _work(self) -> None:
        while (job_id := self._next()) is not None:
            job = self._jobs[job_id]
            try:
                outcome, status = job["fn"](*job["args"]), "done"
            except Exception as exc:  # noqa: BLE001 - a job's failure is its result
                outcome, status = exc, "failed"
            with self._lock:
                job["result"] = outcome
                job["status"] = status
                self._lock.notify_all()
