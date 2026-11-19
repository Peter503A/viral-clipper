"""Thread-safe in-memory job store with a single background worker thread."""
from __future__ import annotations

import threading
import traceback
import uuid
from queue import Queue
from typing import Callable, Optional

from .models import Job, JobKind, JobState


class JobStore:
    """Holds jobs and runs them one at a time on a worker thread.

    Clipping is CPU/IO heavy, so a single worker keeps the machine responsive
    and avoids two ffmpeg/whisper runs fighting over resources. The HTTP layer
    stays non-blocking: it enqueues a job and polls status.
    """

    def __init__(self, runner: Callable[["JobStore", Job], None]) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: "Queue[str]" = Queue()
        self._runner = runner
        self._worker = threading.Thread(target=self._work_loop, daemon=True)
        self._worker.start()

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job: Job,
        *,
        state: Optional[JobState] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update job fields under lock (called from the worker thread)."""
        with self._lock:
            if state is not None:
                job.state = state
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            if message is not None:
                job.message = message

    def _work_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            try:
                self._runner(self, job)
            except Exception as exc:  # noqa: BLE001 - surface any failure
                with self._lock:
                    job.state = JobState.ERROR
                    job.error = str(exc)
                    job.message = "Failed: " + str(exc)
                traceback.print_exc()
            finally:
                self._queue.task_done()
