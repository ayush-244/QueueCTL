"""Enqueue sample jobs for manual testing. Run from project root."""

import json
import subprocess
import sys

CLI = [sys.executable, "-m", "queuectl.cli"]

JOBS = [
    {"id": "hello-1", "command": "echo Hello from job 1"},
    {"id": "hello-2", "command": "echo Hello from job 2"},
    {"id": "hello-3", "command": "echo Hello from job 3"},
    {"id": "fail-demo", "command": "exit 1", "max_retries": 3},
    {"id": "slow-demo", "command": f'{sys.executable} -c "import time; time.sleep(10)"'},
]


def main() -> None:
    for job in JOBS:
        r = subprocess.run(CLI + ["enqueue", json.dumps(job)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL {job['id']}: {r.stderr}", file=sys.stderr)
            sys.exit(1)
        print(f"Enqueued {job['id']}")

    subprocess.run(CLI + ["status"], check=False)
    print()
    print("Sample jobs enqueued. Start a worker in another terminal:")
    print("  python -m queuectl.cli worker start")
    print()
    print("Or with 3 workers:")
    print("  python -m queuectl.cli worker start --count 3")


if __name__ == "__main__":
    main()
