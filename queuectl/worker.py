"""Worker loop, heartbeat thread, and signal handling."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from multiprocessing import Process

from queuectl import queue_ops

POLL_INTERVAL_SECONDS = 1.0
HEARTBEAT_INTERVAL_SECONDS = 5.0

_children: list[Process] = []
_shutdown_requested = False


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
    while not _shutdown_requested:
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


def _request_shutdown(signum=None, frame=None) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    for child in _children:
        if child.is_alive():
            child.terminate()


def start_workers(count: int = 1) -> None:
    """Start one or more worker processes in the foreground."""
    global _children

    if count == 1:
        run_worker_loop()
        return

    signal.signal(signal.SIGINT, _request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_shutdown)

    _children = []
    for _ in range(count):
        process = Process(target=run_worker_loop)
        process.start()
        _children.append(process)

    try:
        while any(child.is_alive() for child in _children):
            for child in _children:
                child.join(timeout=0.5)
    except KeyboardInterrupt:
        _request_shutdown()
    finally:
        for child in _children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=5)


if __name__ == "__main__":
    run_worker_loop()
