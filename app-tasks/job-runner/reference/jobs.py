"""A small job runner: jobs wait in a queue and run one at a time, highest
priority first, on one worker thread. Reference solution of the
job-runner app task (all three milestones)."""

from __future__ import annotations

import itertools
import threading

_ENDED = ("done", "failed", "cancelled")


class Runner:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._queue: list[int] = []
        self._jobs: dict[int, dict] = {}
        self._lock = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopping = False

    def submit(self, fn, *args, priority: int = 0, retries: int = 0) -> int:
        """Queue `fn(*args)` and return the job's id: 1, 2, 3..."""
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError("priority must be an int")
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
            raise ValueError("retries must be a whole number, 0 or more")
        with self._lock:
            job_id = next(self._ids)
            self._jobs[job_id] = {
                "fn": fn,
                "args": args,
                "status": "queued",
                "result": None,
                "priority": priority,
                "retries": retries,
                "attempts": 0,
            }
            self._queue.append(job_id)
            self._lock.notify_all()
            return job_id

    def _order(self) -> list[int]:
        # Highest priority first; the same priority, the lower id first.
        return sorted(self._queue, key=lambda j: (-self._jobs[j]["priority"], j))

    def queued(self) -> list[int]:
        with self._lock:
            return self._order()

    def status(self, job_id: int) -> str:
        with self._lock:
            return self._jobs[job_id]["status"]

    def result(self, job_id: int):
        with self._lock:
            return self._jobs[job_id]["result"]

    def attempts(self, job_id: int) -> int:
        with self._lock:
            return self._jobs[job_id]["attempts"]

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            job = self._jobs[job_id]
            if job["status"] != "queued":
                return False
            self._queue.remove(job_id)
            job["status"] = "cancelled"
            self._lock.notify_all()
            return True

    def wait(self, job_id: int, timeout: float = 10.0) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: self._jobs[job_id]["status"] in _ENDED, timeout)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._work, daemon=True)
            self._thread.start()

    def stop(self) -> None:
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
            job_id = self._order()[0]
            self._queue.remove(job_id)
            self._jobs[job_id]["status"] = "running"
            return job_id

    def _work(self) -> None:
        while (job_id := self._next()) is not None:
            job = self._jobs[job_id]
            while True:
                with self._lock:
                    job["attempts"] += 1
                try:
                    outcome, status = job["fn"](*job["args"]), "done"
                except Exception as exc:  # noqa: BLE001 - a job's failure is its result
                    outcome, status = exc, "failed"
                if status == "done" or job["attempts"] > job["retries"]:
                    break
            with self._lock:
                job["result"] = outcome
                job["status"] = status
                self._lock.notify_all()
