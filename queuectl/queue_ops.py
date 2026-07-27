"""Enqueue, claim, complete, fail, and DLQ retry operations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from queuectl.config import get_backoff_base, get_max_retries
from queuectl.db import get_connection, init_db, row_to_dict
from queuectl.models import (
    ALL_STATES,
    STATE_PENDING,
    Job,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_job(job_json: str) -> Job:
    data = json.loads(job_json)
    job_id = data.get("id") or str(uuid.uuid4())
    command = data["command"]

    max_retries = data.get("max_retries", get_max_retries())
    backoff_base = data.get("backoff_base", get_backoff_base())
    now = utc_now_iso()

    job = Job(
        id=job_id,
        command=command,
        state=STATE_PENDING,
        attempts=0,
        max_retries=max_retries,
        backoff_base=backoff_base,
        created_at=now,
        updated_at=now,
    )

    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                id, command, state, attempts, max_retries, backoff_base,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.command,
                job.state,
                job.attempts,
                job.max_retries,
                job.backoff_base,
                job.created_at,
                job.updated_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return job


def list_jobs_by_state(state: str) -> list[Job]:
    if state not in ALL_STATES:
        raise ValueError(f"Invalid state: {state}")

    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC",
            (state,),
        ).fetchall()
        return [Job.from_row(row_to_dict(row)) for row in rows]
    finally:
        conn.close()


def get_job_counts() -> dict[str, int]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT state, COUNT(*) AS cnt FROM jobs GROUP BY state"
        ).fetchall()
        counts = {s: 0 for s in ALL_STATES}
        for row in rows:
            counts[row["state"]] = row["cnt"]
        return counts
    finally:
        conn.close()


def get_live_worker_count() -> int:
    """Stub for Phase 2 — returns 0 until PID files are implemented."""
    return 0
