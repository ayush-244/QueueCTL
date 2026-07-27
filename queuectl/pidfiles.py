"""Write, read, and cleanup worker PID files."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from queuectl.db import RUNTIME_DIR

WORKERS_DIR = RUNTIME_DIR / "workers"


def ensure_workers_dir() -> None:
    WORKERS_DIR.mkdir(parents=True, exist_ok=True)


def pid_file_path(pid: int) -> Path:
    return WORKERS_DIR / f"{pid}.pid"


def stop_file_path(pid: int) -> Path:
    return WORKERS_DIR / f"{pid}.stop"


def write_pid_file(pid: int | None = None) -> Path:
    if pid is None:
        pid = os.getpid()
    ensure_workers_dir()
    path = pid_file_path(pid)
    path.write_text(str(pid), encoding="utf-8")
    return path


def remove_pid_file(pid: int | None = None) -> None:
    if pid is None:
        pid = os.getpid()
    pid_file_path(pid).unlink(missing_ok=True)
    stop_file_path(pid).unlink(missing_ok=True)


def request_worker_stop(pid: int) -> None:
    ensure_workers_dir()
    stop_file_path(pid).write_text("1", encoding="utf-8")


def stop_requested(pid: int | None = None) -> bool:
    if pid is None:
        pid = os.getpid()
    return stop_file_path(pid).exists()


def list_worker_pids() -> list[int]:
    ensure_workers_dir()
    pids: list[int] = []
    for path in WORKERS_DIR.glob("*.pid"):
        try:
            pids.append(int(path.stem))
        except ValueError:
            path.unlink(missing_ok=True)
    return pids


def is_process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cleanup_stale_pid_files() -> list[int]:
    """Remove PID files for processes that are no longer running."""
    removed: list[int] = []
    for pid in list_worker_pids():
        if not is_process_alive(pid):
            remove_pid_file(pid)
            removed.append(pid)
    return removed


def count_live_workers() -> int:
    cleanup_stale_pid_files()
    return sum(1 for pid in list_worker_pids() if is_process_alive(pid))
