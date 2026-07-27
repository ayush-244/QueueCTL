"""Phase 10: interface contract conformance checks."""

from __future__ import annotations

import json

from tests.helpers import enqueue, reset_runtime, run_cli, stop_workers


def test_list_json_stdout_is_only_json() -> None:
    reset_runtime()
    enqueue({"id": "iface1", "command": "echo ok"})

    r = run_cli("list", "--state", "pending", "--json")
    assert r.returncode == 0
    assert r.stderr == ""
    parsed = json.loads(r.stdout.strip())
    assert isinstance(parsed, list)
    assert parsed[0]["id"] == "iface1"
    stop_workers()


def test_dlq_list_json_stdout_is_only_json() -> None:
    r = run_cli("dlq", "list", "--json")
    assert r.returncode == 0
    assert r.stderr == ""
    parsed = json.loads(r.stdout.strip())
    assert isinstance(parsed, list)


def test_status_is_human_readable() -> None:
    r = run_cli("status")
    assert r.returncode == 0
    assert "Job counts:" in r.stdout
    assert not r.stdout.strip().startswith("[")


if __name__ == "__main__":
    test_list_json_stdout_is_only_json()
    test_dlq_list_json_stdout_is_only_json()
    test_status_is_human_readable()
    print("OK")
