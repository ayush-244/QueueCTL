"""Enqueue, claim, complete, fail, and DLQ retry operations."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from queuectl import pidfiles
from queuectl.config import get_backoff_base, get_max_retries
from queuectl.db import get_connection, init_db, row_to_dict
from queuectl.models import (
    ALL_STATES,
    STATE_COMPLETED,
    STATE_DEAD,
    STATE_FAILED,
    STATE_PENDING,
    STATE_PROCESSING,
    Job,
)

LEASE_SECONDS = 15

CLAIM_SQL = """
UPDATE jobs
SET state = 'processing',
    worker_pid = :pid,
    lease_expires_at = :lease_expiry,
    updated_at = :now
WHERE id = (
  SELECT id FROM jobs
  WHERE (state = 'pending')
     OR (state = 'failed' AND next_retry_at <= :now)
     OR (state = 'processing' AND lease_expires_at <= :now)
  ORDER BY created_at ASC
  LIMIT 1
)
RETURNING *;
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_expiry_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return (current + timedelta(seconds=LEASE_SECONDS)).isoformat()


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


def claim_job(pid: int | None = None) -> Job | None:
    """Atomically claim the next eligible job."""
    if pid is None:
        pid = os.getpid()

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease_expiry = _lease_expiry_iso(now_dt)

    init_db()
    conn = get_connection()
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                CLAIM_SQL,
                {"pid": pid, "lease_expiry": lease_expiry, "now": now},
            ).fetchone()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        if row is None:
            return None
        return Job.from_row(row_to_dict(row))
    finally:
        conn.close()


def complete_job(job_id: str) -> None:
    now = utc_now_iso()
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE jobs
            SET state = ?, updated_at = ?, worker_pid = NULL,
                lease_expires_at = NULL, last_error = NULL
            WHERE id = ?
            """,
            (STATE_COMPLETED, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def fail_job(job_id: str, error: str | None = None) -> None:
    """Mark a job failed with exponential backoff, or dead if retries exhausted."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return

        job = Job.from_row(row_to_dict(row))
        attempts = job.attempts + 1

        if attempts >= job.max_retries:
            state = STATE_DEAD
            next_retry_at = None
        else:
            state = STATE_FAILED
            delay_seconds = job.backoff_base ** attempts
            next_retry_at = (now_dt + timedelta(seconds=delay_seconds)).isoformat()

        conn.execute(
            """
            UPDATE jobs
            SET state = ?, attempts = ?, updated_at = ?, worker_pid = NULL,
                lease_expires_at = NULL, last_error = ?, next_retry_at = ?
            WHERE id = ?
            """,
            (state, attempts, now, error, next_retry_at, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def renew_lease(job_id: str, pid: int | None = None) -> None:
    """Extend the lease on a processing job."""
    if pid is None:
        pid = os.getpid()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    lease_expiry = _lease_expiry_iso(now_dt)

    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE jobs
            SET lease_expires_at = ?, updated_at = ?, worker_pid = ?
            WHERE id = ? AND state = 'processing'
            """,
            (lease_expiry, now, pid, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def dlq_retry_job(job_id: str) -> Job:
    """Re-enqueue a dead job with a fresh retry budget."""
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND state = ?", (job_id, STATE_DEAD)
        ).fetchone()
        if row is None:
            raise ValueError(f"Job '{job_id}' not found in dead letter queue")

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE jobs
            SET state = ?, attempts = 0, updated_at = ?,
                next_retry_at = NULL, last_error = NULL,
                worker_pid = NULL, lease_expires_at = NULL
            WHERE id = ?
            """,
            (STATE_PENDING, now, job_id),
        )
        conn.commit()

        updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.from_row(row_to_dict(updated))
    finally:
        conn.close()


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


def list_dlq_jobs() -> list[Job]:
    return list_jobs_by_state(STATE_DEAD)


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
    return pidfiles.count_live_workers()
