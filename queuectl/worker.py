"""Worker loop, heartbeat thread, and signal handling."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from multiprocessing import Process

from queuectl import pidfiles
from queuectl import queue_ops

POLL_INTERVAL_SECONDS = 1.0
HEARTBEAT_INTERVAL_SECONDS = 5.0

_children: list[Process] = []


def _heartbeat_loop(job_id: str, pid: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        queue_ops.renew_lease(job_id, pid)


def _run_command(command: str) -> subprocess.CompletedProcess:
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.run(command, shell=True, **kwargs)


def _execute_job(job, pid: int) -> int:
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(job.id, pid, stop_event),
        daemon=True,
    )
    heartbeat.start()
    try:
        result = _run_command(job.command)
        return result.returncode
    finally:
        stop_event.set()
        heartbeat.join(timeout=1.0)


def _interruptible_sleep(
    seconds: float,
    pid: int,
    shutdown: dict[str, bool],
) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if shutdown["requested"] or pidfiles.stop_requested(pid):
            return
        time.sleep(min(0.1, deadline - time.time()))


def run_worker_loop() -> None:
    """Poll for jobs, execute commands, and update state."""
    shutdown = {"requested": False}

    def _handle_signal(signum, frame):
        shutdown["requested"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    pid = os.getpid()
    pidfiles.write_pid_file(pid)
    try:
        while not shutdown["requested"] and not pidfiles.stop_requested(pid):
            job = queue_ops.claim_job(pid=pid)
            if job is None:
                _interruptible_sleep(POLL_INTERVAL_SECONDS, pid, shutdown)
                continue

            returncode = _execute_job(job, pid)
            if returncode == 0:
                queue_ops.complete_job(job.id)
            else:
                queue_ops.fail_job(
                    job.id,
                    error=f"Command exited with code {returncode}",
                )
            if shutdown["requested"] or pidfiles.stop_requested(pid):
                break
    finally:
        pidfiles.remove_pid_file(pid)


def _stop_children(signum=None, frame=None) -> None:
    for child in _children:
        if child.is_alive():
            pidfiles.request_worker_stop(child.pid)
            if sys.platform != "win32":
                try:
                    os.kill(child.pid, signal.SIGTERM)
                except OSError:
                    child.terminate()


def start_workers(count: int = 1) -> None:
    """Start one or more worker processes in the foreground."""
    global _children

    if count == 1:
        run_worker_loop()
        return

    signal.signal(signal.SIGINT, _stop_children)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop_children)

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
        _stop_children()
    finally:
        for child in _children:
            child.join(timeout=10)


def stop_all_workers(wait_seconds: float = 3.0) -> list[int]:
    """Send SIGTERM to all workers registered via PID files."""
    pidfiles.cleanup_stale_pid_files()
    pids = pidfiles.list_worker_pids()
    signalled: list[int] = []

    for pid in pids:
        if not pidfiles.is_process_alive(pid):
            pidfiles.remove_pid_file(pid)
            continue
        pidfiles.request_worker_stop(pid)
        try:
            if sys.platform != "win32":
                if hasattr(signal, "SIGTERM"):
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGINT)
            signalled.append(pid)
        except OSError:
            pidfiles.remove_pid_file(pid)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        pidfiles.cleanup_stale_pid_files()
        if not any(pidfiles.is_process_alive(pid) for pid in signalled):
            break
        time.sleep(0.2)

    pidfiles.cleanup_stale_pid_files()
    return signalled


if __name__ == "__main__":
    run_worker_loop()
