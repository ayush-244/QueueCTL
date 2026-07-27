"""Worker loop, heartbeat thread, and signal handling."""

from __future__ import annotations

import os
import subprocess
import threading
import time

from queuectl import queue_ops

POLL_INTERVAL_SECONDS = 1.0
HEARTBEAT_INTERVAL_SECONDS = 5.0


def _heartbeat_loop(job_id: str, pid: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        queue_ops.renew_lease(job_id, pid)


def _execute_job(job, pid: int) -> int:
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(job.id, pid, stop_event),
        daemon=True,
    )
    heartbeat.start()
    try:
        result = subprocess.run(job.command, shell=True)
        return result.returncode
    finally:
        stop_event.set()
        heartbeat.join(timeout=1.0)


def run_worker_loop() -> None:
    """Poll for jobs, execute commands, and update state."""
    pid = os.getpid()
    while True:
        job = queue_ops.claim_job(pid=pid)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        returncode = _execute_job(job, pid)
        if returncode == 0:
            queue_ops.complete_job(job.id)
        else:
            queue_ops.fail_job(
                job.id,
                error=f"Command exited with code {returncode}",
            )


def start_workers(count: int = 1) -> None:
    """Start one or more worker processes (Phase 3: count=1 only)."""
    if count != 1:
        raise NotImplementedError("--count > 1 is implemented in Phase 7")
    run_worker_loop()


if __name__ == "__main__":
    run_worker_loop()
