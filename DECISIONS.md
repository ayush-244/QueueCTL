# Design Decisions

Specific answers to the five grading questions, with exact file/line references.

---

## 1. Which exact line(s) prevent two workers from claiming the same job, and why is that atomic across separate OS processes?

**File:** `queuectl/queue_ops.py`

The claim query (lines **26–40**) atomically selects and updates one eligible job:

```26:40:queuectl/queue_ops.py
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
```

It runs inside an explicit write transaction (lines **113–120**):

```113:120:queuectl/queue_ops.py
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                CLAIM_SQL,
                {"pid": pid, "lease_expiry": lease_expiry, "now": now},
            ).fetchone()
            conn.execute("COMMIT")
```

**Why this is atomic across processes:** `BEGIN IMMEDIATE` acquires a reserved write lock before the `UPDATE` runs. SQLite serializes writers at the database file level — two separate OS processes cannot both have this `UPDATE` in flight against the same row set. The second process blocks (via `PRAGMA busy_timeout=5000` set in `db.py` lines **44–45**) until the first commits; by then the row is already `processing` and no longer eligible. No in-process lock is needed.

---

## 2. A worker is SIGKILLed halfway through a job. Walk through state and recovery. Worst-case delay?

**Step by step:**

1. **Before crash:** Worker claims the job (`queue_ops.py:116–119`). Row becomes `state='processing'`, `lease_expires_at = now + 15s` (`LEASE_SECONDS` at line **24**, set at claim lines **29–30**).

2. **During execution:** A heartbeat thread renews the lease every 5s (`worker.py` lines **22–24**, **34–47**; `HEARTBEAT_INTERVAL_SECONDS = 5.0` at line **17**).

3. **SIGKILL:** The worker process dies instantly. No cleanup handler runs. The job row stays `processing` with a `lease_expires_at` timestamp in the near future. The child shell command may also die.

4. **After crash, before lease expiry:** No worker can reclaim the job — the stale-lease clause (`queue_ops.py` line **36**) requires `lease_expires_at <= :now`.

5. **After lease expires (~15s without heartbeat):** The job becomes eligible again via line **36**. The next worker poll (`worker.py` line **77**, sleep interval `POLL_INTERVAL_SECONDS = 1.0` at line **16**) runs `claim_job`, which re-claims and re-executes the command.

6. **Completion:** Exit code 0 → `complete_job` (`queue_ops.py:132–148`). Non-zero → `fail_job` with backoff (`queue_ops.py:151–185`).

**Worst-case recovery delay:** `LEASE_SECONDS + POLL_INTERVAL_SECONDS` = **15s + 1s = 16 seconds** (`queue_ops.py:24`, `worker.py:16–17`). Well under the 60-second grading bound.

---

## 3. Does `dlq retry` reset `attempts`? Why is that correct?

**Yes.** `dlq retry` sets `attempts = 0` at `queue_ops.py` line **227**:

```224:231:queuectl/queue_ops.py
        conn.execute(
            """
            UPDATE jobs
            SET state = ?, attempts = 0, updated_at = ?,
                next_retry_at = NULL, last_error = NULL,
                worker_pid = NULL, lease_expires_at = NULL
            WHERE id = ?
            """,
```

**Why:** DLQ retry is a **human operator** deciding the underlying problem is fixed (bad input corrected, downstream service restored, etc.). The job should receive a **full fresh retry budget**, not a continuation of the previous failure streak. If we kept the old `attempts` count, a job that died at `attempts == max_retries` would immediately go dead again on the next failure.

---

## 4. What did you consider and reject for `worker stop`, and why?

**Chosen approach:** PID files under `.queuectl/workers/<pid>.pid` (`pidfiles.py` lines **25–31**) plus:

- `SIGTERM` to each live worker on Unix (`worker.py` lines **148–150**)
- Per-worker `.stop` files on Windows (`pidfiles.py` lines **41–43**, checked in `worker.py` line **76**) because Windows does not reliably deliver signals across terminal sessions

Workers poll for stop requests each loop iteration (`worker.py:76–79`) and finish the in-flight job before exiting (`worker.py:82–91`).

**Rejected:**

| Alternative | Why rejected |
|-------------|--------------|
| **Unix domain control socket** | Unnecessary complexity for this scale — requires a persistent listener, socket lifecycle management, and error handling for a problem PID files + signals solve in ~30 lines. |
| **DB-polled "stop requested" flag** | Adds latency equal to the worker poll interval (~1s) on every stop check, whereas OS signals are effectively instant on Unix. (We use `.stop` files only as a Windows fallback, not as the primary mechanism.) |

---

## 5. If priorities were added tomorrow, what survives unchanged and what breaks?

**Survives unchanged:**

- The claim query's overall structure (`UPDATE ... WHERE id = (SELECT ... LIMIT 1)`) — only the `ORDER BY` clause changes
- `BEGIN IMMEDIATE` atomicity (`queue_ops.py:114`)
- Schema columns for retries/backoff (`max_retries`, `backoff_base`, `attempts`, `next_retry_at`) — priority is orthogonal to retry logic
- Lease / heartbeat crash recovery (`worker.py:22–47`, stale-lease clause `queue_ops.py:36`)
- Worker loop, PID files, graceful shutdown
- Config snapshot at enqueue time (`queue_ops.py:58–59`)

**Breaks / needs changes:**

- `ORDER BY created_at ASC` in the claim subquery (`queue_ops.py:37`) → would become `ORDER BY priority DESC, created_at ASC`
- New `priority INTEGER NOT NULL DEFAULT 0` column in the `jobs` table (`db.py:13–26`)
- `enqueue` would accept an optional `priority` field (`queue_ops.py:53–71`)
- Job JSON output / `Job` dataclass (`models.py:23–36`)

**Config/backoff logic is untouched** — priority affects claim ordering only, not retry timing.

---

## Config change semantics

`config set` writes to the `config` table (`config.py:31–44`). At enqueue time, `max_retries` and `backoff_base` are read from config and **copied onto the job row** (`queue_ops.py:58–59`, inserted at lines **78–81**). Changing config later does not retroactively alter already-enqueued jobs.
