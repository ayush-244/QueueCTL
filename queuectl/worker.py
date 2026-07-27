"""Worker loop, heartbeat thread, and signal handling."""

from __future__ import annotations

import subprocess
import sys
import time

from queuectl import queue_ops


POLL_INTERVAL_SECONDS = 1.0


def run_worker_loop() -> None:
    """Poll for jobs, execute commands, and update state."""
    pid = __import__("os").getpid()
    while True:
        job = queue_ops.claim_job(pid=pid)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        result = subprocess.run(job.command, shell=True)
        if result.returncode == 0:
            queue_ops.complete_job(job.id)
        else:
            queue_ops.fail_job(
                job.id,
                error=f"Command exited with code {result.returncode}",
            )


def start_workers(count: int = 1) -> None:
    """Start one or more worker processes (Phase 3: count=1 only)."""
    if count != 1:
        raise NotImplementedError("--count > 1 is implemented in Phase 7")
    run_worker_loop()


if __name__ == "__main__":
    run_worker_loop()
