"""Phase 9: full-restart persistence verification."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from tests.helpers import RUNTIME, count_state, enqueue, reset_runtime, run_cli, start_worker, stop_workers

PYTHON = sys.executable


def test_full_restart_survival() -> None:
    reset_runtime()

    for i in range(5):
        enqueue(
            {
                "id": f"restart{i}",
                "command": f'{PYTHON} -c "import time; time.sleep(2)"',
            }
        )

    worker = start_worker()
    time.sleep(0.5)
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(worker.pid)], check=False)
    else:
        os.kill(worker.pid, signal.SIGKILL)
    worker.wait(timeout=10)

    assert RUNTIME.joinpath("queuectl.db").exists()

    remaining = sum(count_state(s) for s in ("pending", "processing", "failed"))
    assert remaining >= 1, "Jobs should persist across worker restart"

    worker2 = start_worker()
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            if count_state("completed") == 5:
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Jobs did not resume after restart")
    finally:
        stop_workers(worker2)


if __name__ == "__main__":
    test_full_restart_survival()
    print("OK")
