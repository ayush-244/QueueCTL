"""Phase 9: full-restart persistence verification."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUNTIME = Path(".queuectl")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "queuectl.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_full_restart_survival() -> None:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)

    for i in range(8):
        job = json.dumps(
            {
                "id": f"restart{i}",
                "command": f'{sys.executable} -c "import time; time.sleep(30)"',
            }
        )
        assert run_cli("enqueue", job).returncode == 0

    worker = subprocess.Popen(
        [sys.executable, "-m", "queuectl.cli", "worker", "start"],
    )
    time.sleep(0.3)
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(worker.pid)], check=False)
    else:
        import os
        import signal

        os.kill(worker.pid, signal.SIGKILL)
    worker.wait(timeout=10)

    assert RUNTIME.joinpath("queuectl.db").exists()

    r = run_cli("status")
    assert "pending:" in r.stdout or "processing:" in r.stdout

    remaining = 0
    for state in ("pending", "processing", "failed"):
        r = run_cli("list", "--state", state, "--json")
        remaining += len(json.loads(r.stdout))
    assert remaining >= 1, "Jobs should persist across worker restart"

    worker2 = subprocess.Popen(
        [sys.executable, "-m", "queuectl.cli", "worker", "start"],
    )
    try:
        for _ in range(120):
            r = run_cli("list", "--state", "completed", "--json")
            if len(json.loads(r.stdout)) == 8:
                break
            time.sleep(1)
        else:
            raise AssertionError("Jobs did not resume after restart")
    finally:
        run_cli("worker", "stop")
        worker2.wait(timeout=10)


if __name__ == "__main__":
    test_full_restart_survival()
    print("OK")
