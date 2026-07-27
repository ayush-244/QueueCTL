"""Automated tests mirroring the grading scenarios (subprocess-driven)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import unittest
from collections import Counter
from pathlib import Path

from tests.helpers import (
    RUNTIME,
    count_state,
    enqueue,
    reset_runtime,
    run_cli,
    start_worker,
    stop_workers,
    wait_for_state,
)

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "ran.log"
PYTHON = sys.executable


class GradingScenarios(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()

    def tearDown(self) -> None:
        stop_workers()

    def test_01_basic_job_completes(self) -> None:
        enqueue({"id": "basic", "command": "echo ok"})
        worker = start_worker()
        try:
            wait_for_state("basic", "completed", timeout=30)
        finally:
            stop_workers(worker)

        r = run_cli("list", "--state", "completed", "--json")
        ids = [j["id"] for j in json.loads(r.stdout)]
        self.assertIn("basic", ids)

    def test_02_failing_job_retries_and_dlq(self) -> None:
        enqueue(
            {
                "id": "failer",
                "command": "exit 1",
                "max_retries": 3,
                "backoff_base": 2,
            }
        )
        worker = start_worker()
        try:
            job = wait_for_state("failer", "dead", timeout=60)
            self.assertEqual(job["attempts"], 3)
        finally:
            stop_workers(worker)

        r = run_cli("dlq", "list", "--json")
        dead = json.loads(r.stdout)
        self.assertTrue(any(j["id"] == "failer" for j in dead))

    def test_03_many_jobs_exactly_once(self) -> None:
        if LOG_FILE.exists():
            LOG_FILE.unlink()

        def append_cmd(jid: str) -> str:
            return f"{PYTHON} -c \"open('ran.log', 'a').write('{jid}\\n')\""

        for i in range(30):
            enqueue({"id": f"job{i:02d}", "command": append_cmd(f"job{i:02d}")})

        worker = start_worker("--count", "3")
        try:
            deadline = time.time() + 90
            while time.time() < deadline:
                if count_state("completed") == 30:
                    break
                time.sleep(0.5)
            else:
                self.fail("Not all jobs completed")

            lines = LOG_FILE.read_text().strip().splitlines()
            self.assertEqual(len(lines), 30)
            self.assertEqual(len(set(lines)), 30)
            dupes = [k for k, v in Counter(lines).items() if v > 1]
            self.assertEqual(dupes, [])
        finally:
            stop_workers(worker)

    def test_04_sigkill_mid_job_recovers(self) -> None:
        enqueue(
            {
                "id": "crashme",
                "command": f'{PYTHON} -c "import time; time.sleep(20)"',
            }
        )
        worker = start_worker()
        time.sleep(2)

        r = run_cli("list", "--state", "processing", "--json")
        self.assertTrue(any(j["id"] == "crashme" for j in json.loads(r.stdout)))

        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(worker.pid)], check=False)
        else:
            os.kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=10)

        r = run_cli("list", "--state", "processing", "--json")
        self.assertTrue(any(j["id"] == "crashme" for j in json.loads(r.stdout)))

        worker2 = start_worker()
        try:
            wait_for_state("crashme", "completed", timeout=45)
        finally:
            stop_workers(worker2)

    def test_05_full_restart_survival(self) -> None:
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

        self.assertTrue(RUNTIME.joinpath("queuectl.db").exists())
        remaining = sum(count_state(s) for s in ("pending", "processing", "failed"))
        self.assertGreaterEqual(remaining, 1)

        worker2 = start_worker()
        try:
            deadline = time.time() + 90
            while time.time() < deadline:
                if count_state("completed") == 5:
                    break
                time.sleep(0.5)
            else:
                self.fail("Jobs did not resume after full restart")
        finally:
            stop_workers(worker2)


class InterfaceContract(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()

    def tearDown(self) -> None:
        stop_workers()

    def test_list_json_stdout_only(self) -> None:
        enqueue({"id": "iface", "command": "echo ok"})
        r = run_cli("list", "--state", "pending", "--json")
        self.assertEqual(r.stderr, "")
        data = json.loads(r.stdout.strip())
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["id"], "iface")

    def test_dlq_list_json_stdout_only(self) -> None:
        r = run_cli("dlq", "list", "--json")
        self.assertEqual(r.stderr, "")
        self.assertIsInstance(json.loads(r.stdout.strip()), list)

    def test_status_human_readable(self) -> None:
        r = run_cli("status")
        self.assertIn("Job counts:", r.stdout)
        self.assertFalse(r.stdout.strip().startswith("["))


if __name__ == "__main__":
    unittest.main()
