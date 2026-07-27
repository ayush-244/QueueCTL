"""Shared helpers for subprocess-driven CLI tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".queuectl"


def cli_command() -> list[str]:
    """Prefer installed `queuectl` binary; fall back to module invocation."""
    import shutil as _shutil

    if _shutil.which("queuectl"):
        return ["queuectl"]
    return [sys.executable, "-m", "queuectl.cli"]


def run_cli(*args: str, timeout: float = 30, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cli_command() + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or ROOT,
    )


def enqueue(job: dict) -> subprocess.CompletedProcess[str]:
    return run_cli("enqueue", json.dumps(job))


def kill_stray_workers() -> None:
    run_cli("worker", "stop")
    if RUNTIME.joinpath("workers").exists():
        for path in (RUNTIME / "workers").glob("*.pid"):
            path.unlink(missing_ok=True)
        for path in (RUNTIME / "workers").glob("*.stop"):
            path.unlink(missing_ok=True)

    if sys.platform == "win32":
        ps = (
            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
            "Where-Object { "
            "$_.CommandLine -like '*queuectl.cli*worker*' -or "
            "$_.CommandLine -like '*multiprocessing.spawn*' "
            "} | ForEach-Object { $_.ProcessId }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
        )
        for line in r.stdout.splitlines():
            if line.strip().isdigit() and int(line.strip()) != os.getpid():
                subprocess.run(["taskkill", "/F", "/PID", line.strip()], check=False)
    else:
        subprocess.run(["pkill", "-f", "queuectl.cli worker"], check=False)


def reset_runtime() -> None:
    kill_stray_workers()
    time.sleep(0.3)
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME, ignore_errors=True)


def start_worker(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        cli_command() + ["worker", "start", *args],
        cwd=ROOT,
    )


def stop_workers(worker: subprocess.Popen | None = None, timeout: float = 15) -> None:
    run_cli("worker", "stop")
    if worker is not None and worker.poll() is None:
        worker.terminate()
        try:
            worker.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            worker.kill()
    kill_stray_workers()


def wait_for_state(job_id: str, state: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = run_cli("list", "--state", state, "--json")
        for job in json.loads(r.stdout):
            if job["id"] == job_id:
                return job
        time.sleep(0.3)
    raise TimeoutError(f"Job {job_id} did not reach state {state!r} within {timeout}s")


def count_state(state: str) -> int:
    r = run_cli("list", "--state", state, "--json")
    return len(json.loads(r.stdout.strip() or "[]"))
