# QueueCTL — Complete Project Guide

This document explains **everything** about the QueueCTL project: what it does, how it works, every file, the database schema, and **step-by-step manual testing commands** (Windows PowerShell + Linux/Mac bash).

---

## Table of contents

1. [What is QueueCTL?](#what-is-queuectl)
2. [Tech stack](#tech-stack)
3. [Project structure (every file)](#project-structure-every-file)
4. [How the system works](#how-the-system-works)
5. [Database schema](#database-schema)
6. [Runtime files (.queuectl/)](#runtime-files-queuectl)
7. [Manual testing — step by step](#manual-testing--step-by-step)
8. [Automated tests](#automated-tests)
9. [Troubleshooting](#troubleshooting)

---

## What is QueueCTL?

QueueCTL is a **CLI-based background job queue**. You enqueue shell commands as jobs; worker processes pick them up, run them, and track success/failure. It supports:

- **Multiple workers** in parallel (separate OS processes)
- **Automatic retries** with exponential backoff
- **Dead Letter Queue (DLQ)** for permanently failed jobs
- **Crash recovery** — if a worker is killed mid-job, the job is reclaimed automatically
- **Persistent storage** — all state survives restarts (SQLite)

There is no web UI, no Redis, no Celery — just Python stdlib + Click + SQLite.

---

## Tech stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Assignment allows your choice |
| CLI framework | Click | Clean subcommands (`worker start`, `dlq list`, etc.) |
| Database | SQLite (WAL mode) | File-based persistence + built-in cross-process locking |
| Workers | `multiprocessing.Process` | Real separate OS processes, not threads |
| Job execution | `subprocess.run(shell=True)` | Shell commands, exit code = success/failure |

---

## Project structure (every file)

```
QueueCTL/
├── queuectl/                  # Main Python package
│   ├── __init__.py
│   ├── cli.py
│   ├── db.py
│   ├── models.py
│   ├── queue_ops.py
│   ├── worker.py
│   ├── config.py
│   └── pidfiles.py
├── tests/
│   ├── helpers.py
│   ├── test_grading_scenarios.py
│   ├── test_interface_contract.py
│   └── test_restart_survival.py
├── scripts/
│   └── demo_setup.py
├── pyproject.toml
├── README.md
├── DECISIONS.md
├── PROJECT_GUIDE.md          # ← this file
└── .gitignore
```

---

### Root files

#### `pyproject.toml`
Package configuration. Defines:
- Project name: `queuectl`
- Dependency: `click>=8.0`
- **Console script:** `queuectl = queuectl.cli:main` — after `pip install -e .`, you can run `queuectl` from the terminal

#### `README.md`
Short submission README: setup, command reference, architecture diagram, how to run tests, demo link placeholder.

#### `DECISIONS.md`
**Required for grading.** Answers 5 design questions with exact file/line references:
1. Atomic job claiming across processes
2. SIGKILL crash recovery walkthrough
3. Why `dlq retry` resets `attempts`
4. Rejected alternatives for `worker stop`
5. What breaks if priorities are added

#### `.gitignore`
Ignores runtime data: `.queuectl/`, `__pycache__/`, `*.db`, `*.log`, virtualenvs, build artifacts.

#### `dry_run.py` (local dev only, not committed)
Optional script to run all verification checks in one go. Safe to delete.

---

### `queuectl/` package — source code

#### `queuectl/__init__.py`
Package marker. Sets `__version__ = "0.1.0"`. No logic.

#### `queuectl/cli.py` — **CLI entrypoint**
All user-facing commands live here (Click framework).

| Command | Function | What it does |
|---------|----------|--------------|
| `enqueue` | `enqueue()` | Parse JSON, call `queue_ops.enqueue_job()`, print JSON |
| `worker start` | `worker_start()` | Call `worker.start_workers(count)` — **blocks in foreground** |
| `worker stop` | `worker_stop()` | Call `worker.stop_all_workers()` |
| `status` | `status()` | Print human-readable job counts + live worker count |
| `list` | `list_jobs()` | List jobs by state; `--json` uses `_emit_json()` (stdout only) |
| `dlq list` | `dlq_list()` | List dead jobs |
| `dlq retry` | `dlq_retry()` | Re-enqueue a dead job |
| `config set` | `config_set()` | Persist config (`max-retries`, `backoff-base`) |

**Key helper:** `_emit_json()` — writes JSON to stdout only (no extra log lines). Required by the grading interface contract.

#### `queuectl/db.py` — **Database layer**
SQLite connection and schema.

| Item | Purpose |
|------|---------|
| `RUNTIME_DIR` | `.queuectl/` directory path |
| `DB_PATH` | `.queuectl/queuectl.db` |
| `SCHEMA_SQL` | `CREATE TABLE` for `jobs` and `config` |
| `get_connection()` | Opens fresh connection with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` |
| `init_db()` | Creates tables if missing |
| `row_to_dict()` | Converts SQLite Row to Python dict |

**Important:** Every operation opens and closes its own connection. No long-lived shared connection — that would break cross-process locking.

#### `queuectl/models.py` — **Data model**
| Item | Purpose |
|------|---------|
| `STATE_*` constants | `pending`, `processing`, `completed`, `failed`, `dead` |
| `Job` dataclass | All job fields with `to_dict()` and `from_row()` |

Job fields: `id`, `command`, `state`, `attempts`, `max_retries`, `backoff_base`, `created_at`, `updated_at`, `next_retry_at`, `lease_expires_at`, `worker_pid`, `last_error`.

#### `queuectl/queue_ops.py` — **Core queue logic** (most important file)
| Function | Purpose |
|----------|---------|
| `CLAIM_SQL` | Atomic `UPDATE ... RETURNING` — claims one eligible job |
| `claim_job()` | Runs claim inside `BEGIN IMMEDIATE` transaction |
| `enqueue_job()` | Insert new job; snapshot `max_retries`/`backoff_base` from config |
| `complete_job()` | Set `state=completed` |
| `fail_job()` | Increment attempts; backoff or move to `dead` |
| `renew_lease()` | Extend `lease_expires_at` during job execution (heartbeat) |
| `dlq_retry_job()` | Reset dead job to `pending`, `attempts=0` |
| `list_jobs_by_state()` | Query jobs by state |
| `get_job_counts()` | Count per state for `status` |
| `get_live_worker_count()` | Count live workers via PID files |

**Constants:** `LEASE_SECONDS = 15` — how long a processing job's claim is valid without heartbeat renewal.

#### `queuectl/worker.py` — **Worker processes**
| Function | Purpose |
|----------|---------|
| `run_worker_loop()` | Main loop: claim → execute → complete/fail; handles signals |
| `start_workers(count)` | Start 1 or N OS processes; parent blocks |
| `stop_all_workers()` | Signal all workers to stop gracefully |
| `_execute_job()` | Run shell command + heartbeat thread |
| `_heartbeat_loop()` | Renew lease every 5 seconds while job runs |
| `_interruptible_sleep()` | Poll loop sleep that checks for stop requests |

**Signal handling:** `SIGINT`/`SIGTERM` set a flag; current job finishes before exit. Stop files (`.stop`) used as Windows fallback.

#### `queuectl/config.py` — **Configuration**
| Function | Purpose |
|----------|---------|
| `get_max_retries()` | Read from DB config table (default: 3) |
| `get_backoff_base()` | Read from DB (default: 2.0) |
| `set_config()` | Write `max-retries` or `backoff-base` to DB |

Config is read **at enqueue time** and copied onto the job row — changes do not affect existing jobs.

#### `queuectl/pidfiles.py` — **Worker discovery for `worker stop`**
| Function | Purpose |
|------|---------|
| `write_pid_file()` | Worker writes `.queuectl/workers/<pid>.pid` on start |
| `remove_pid_file()` | Cleanup on exit |
| `request_worker_stop()` | Write `.queuectl/workers/<pid>.stop` file |
| `stop_requested()` | Worker checks if stop was requested |
| `list_worker_pids()` | Read all PID files |
| `is_process_alive()` | Check if OS process is still running |
| `count_live_workers()` | Count for `status` command |

---

### `tests/` — automated test suite

#### `tests/helpers.py`
Shared utilities for all tests:
- `cli_command()` — finds `queuectl` binary or falls back to `python -m queuectl.cli`
- `run_cli()`, `enqueue()`, `start_worker()`, `stop_workers()`
- `reset_runtime()` — clean `.queuectl/` and kill orphan workers
- `wait_for_state()`, `count_state()`

#### `tests/test_grading_scenarios.py`
**Main test file** — mirrors the 5 grading scenarios:
1. Basic job completes
2. Failing job → backoff → DLQ
3. 30 jobs / 3 workers, exactly-once
4. SIGKILL mid-job recovery
5. Full restart survival

Also tests interface contract (`--json` stdout-only).

#### `tests/test_interface_contract.py`
Phase 10 checks: `list --json` and `dlq list --json` produce clean stdout.

#### `tests/test_restart_survival.py`
Standalone restart persistence test.

---

### `scripts/demo_setup.py`
Enqueues 5 sample jobs for quick manual testing:
- 3 echo jobs (succeed quickly)
- 1 failing job (`exit 1`)
- 1 slow job (10s sleep)

---

## How the system works

### Job lifecycle

```
pending ──claim──► processing ──exit 0──► completed
                      │
                      └──exit non-zero──► failed ──backoff elapsed──► (retry)
                                            │
                                            └──attempts >= max_retries──► dead (DLQ)
                                                                               │
                                                                    dlq retry ──► pending
```

### Claiming (the heart of the system)

Every second, each worker runs `claim_job()`:
1. `BEGIN IMMEDIATE` — acquire write lock
2. `UPDATE jobs SET state='processing' WHERE id = (SELECT id FROM jobs WHERE eligible ... LIMIT 1) RETURNING *`
3. `COMMIT`

Only one OS process can hold the write lock at a time → **no duplicate execution**.

Eligible jobs:
- `state = 'pending'`
- `state = 'failed'` AND `next_retry_at <= now`
- `state = 'processing'` AND `lease_expires_at <= now` (stale lease — crash recovery)

### Crash recovery

1. Worker claims job, sets `lease_expires_at = now + 15s`
2. Heartbeat thread renews lease every 5s while job runs
3. Worker SIGKILLed → heartbeat stops → lease expires after ~15s
4. Next worker poll reclaims job via stale-lease clause
5. **Worst case: 16 seconds** (15s lease + 1s poll)

### Retry backoff

On failure: `delay = backoff_base ^ attempts` seconds

With `backoff_base=2`:
- 1st failure (attempts=1): retry after 2s
- 2nd failure (attempts=2): retry after 4s
- 3rd failure (attempts=3): `attempts >= max_retries` → `dead`

---

## Database schema

### `jobs` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Unique job ID |
| `command` | TEXT | Shell command to execute |
| `state` | TEXT | `pending`/`processing`/`completed`/`failed`/`dead` |
| `attempts` | INTEGER | Number of failed execution attempts |
| `max_retries` | INTEGER | Max attempts before DLQ (snapshotted at enqueue) |
| `backoff_base` | REAL | Backoff base (snapshotted at enqueue) |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `next_retry_at` | TEXT | When a failed job becomes claimable again |
| `lease_expires_at` | TEXT | When a processing claim becomes stale |
| `worker_pid` | INTEGER | PID of worker currently holding the job |
| `last_error` | TEXT | Last error message |

### `config` table

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | e.g. `max_retries`, `backoff_base` |
| `value` | TEXT | String value |

---

## Runtime files (.queuectl/)

Created automatically in your **current working directory** when you run any command:

```
.queuectl/
├── queuectl.db          # SQLite database (all job state)
├── queuectl.db-wal      # WAL journal (auto-managed by SQLite)
└── workers/
    ├── 12345.pid        # Worker PID file (one per worker process)
    └── 12345.stop       # Stop request file (written by worker stop)
```

**Delete `.queuectl/` to reset everything** (fresh queue).

---

## Manual testing — step by step

> **Tip (Windows):** If `queuectl` is not found, use `python -m queuectl.cli` instead of `queuectl` everywhere below.
>
> **Tip (PowerShell JSON):** Use a variable to avoid quote issues:
> ```powershell
> $job = '{"id":"job1","command":"echo hello"}'
> python -m queuectl.cli enqueue $job
> ```

Open **two terminals**. In both, run:
```powershell
cd c:\Users\shlok\Desktop\QueueCTL
```

---

### Test 0: Install and verify

```powershell
pip install -e .
python -m queuectl.cli --help
```

You should see: `enqueue`, `worker`, `status`, `list`, `dlq`, `config`.

---

### Test 1: Basic job completes

**Terminal 1:**
```powershell
# Clean slate
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

# Enqueue
$job = '{"id":"hello","command":"echo Hello World"}'
python -m queuectl.cli enqueue $job

# Check it's pending
python -m queuectl.cli list --state pending

# Start worker (blocks — leave this running)
python -m queuectl.cli worker start
```

**Terminal 2:**
```powershell
python -m queuectl.cli status
python -m queuectl.cli list --state completed --json
```

Expected: job moves from `pending` → `completed`. Worker prints `Hello World`.

---

### Test 2: Multiple workers, parallel execution

**Terminal 1** (stop previous worker with Ctrl+C first):
```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

# Enqueue 10 quick jobs
1..10 | ForEach-Object {
    $j = "{`"id`":`"job$_`",`"command`":`"echo job$_`"}"
    python -m queuectl.cli enqueue $j
}

python -m queuectl.cli worker start --count 3
```

**Terminal 2:**
```powershell
python -m queuectl.cli status
python -m queuectl.cli list --state completed --json
```

Expected: all 10 jobs complete, no duplicates.

---

### Test 3: Failing job → backoff → DLQ

**Terminal 1:**
```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

$fail = '{"id":"bad-job","command":"exit 1","max_retries":3,"backoff_base":2}'
python -m queuectl.cli enqueue $fail

python -m queuectl.cli worker start
```

**Terminal 2** (watch it retry):
```powershell
# Run repeatedly to watch state changes
python -m queuectl.cli status
python -m queuectl.cli list --state failed --json
python -m queuectl.cli list --state dead --json
python -m queuectl.cli dlq list --json
```

Expected timeline:
- Fails → `failed` (wait ~2s)
- Fails → `failed` (wait ~4s)
- Fails → `dead` (in DLQ)

Stop worker in Terminal 1 with Ctrl+C when done.

---

### Test 4: DLQ retry

```powershell
python -m queuectl.cli dlq retry bad-job
python -m queuectl.cli list --state pending --json
```

Expected: job back to `pending` with `attempts: 0`.

Start worker again to run it:
```powershell
python -m queuectl.cli worker start
```

---

### Test 5: Graceful shutdown (`worker stop`)

**Terminal 1:**
```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

$slow = '{"id":"slow","command":"python -c \"import time; time.sleep(10)\""}'
python -m queuectl.cli enqueue $slow

python -m queuectl.cli worker start
```

**Terminal 2** (while job is running):
```powershell
python -m queuectl.cli worker stop
python -m queuectl.cli status
python -m queuectl.cli list --state completed --json
```

Expected: worker finishes the 10s job, then exits. Job is `completed`. No orphan PID files.

---

### Test 6: Crash recovery (SIGKILL)

**Terminal 1:**
```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

$crash = '{"id":"crashme","command":"python -c \"import time; time.sleep(30)\""}'
python -m queuectl.cli enqueue $crash

python -m queuectl.cli worker start
```

**Terminal 2** (after ~2 seconds, find worker PID and kill it):
```powershell
python -m queuectl.cli list --state processing --json
# Note the worker_pid, then:
taskkill /F /PID <worker-pid>

# Job should still be 'processing' immediately
python -m queuectl.cli list --state processing --json

# Wait ~20 seconds, then start a new worker
python -m queuectl.cli worker start
```

Expected: after ~16s, a new worker reclaims and completes the job.

---

### Test 7: Config changes

```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

python -m queuectl.cli config set max-retries 5
python -m queuectl.cli config set backoff-base 3

$job = '{"id":"cfg-test","command":"echo ok"}'
python -m queuectl.cli enqueue $job
python -m queuectl.cli list --state pending --json
```

Expected: job has `max_retries: 5`, `backoff_base: 3.0` even if you change config later.

---

### Test 8: Full restart survival

```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue

# Enqueue jobs
1..5 | ForEach-Object {
    $j = "{`"id`":`"r$_`",`"command`":`"echo restart$_`"}"
    python -m queuectl.cli enqueue $j
}

# Start worker, then kill it hard
python -m queuectl.cli worker start
# Ctrl+C or taskkill in another terminal

# Verify jobs still in DB
python -m queuectl.cli status

# Start fresh workers — jobs should complete
python -m queuectl.cli worker start --count 2
```

---

### Quick demo script

```powershell
Remove-Item -Recurse -Force .queuectl -ErrorAction SilentlyContinue
python scripts/demo_setup.py
python -m queuectl.cli worker start --count 2
```

---

### Linux / Mac (bash) equivalents

```bash
cd QueueCTL
pip install -e .

# Enqueue
queuectl enqueue '{"id":"job1","command":"echo hello"}'

# Workers
queuectl worker start --count 3        # terminal 1
queuectl worker stop                   # terminal 2
queuectl status
queuectl list --state completed --json

# Crash test
queuectl enqueue '{"id":"crash","command":"sleep 30"}'
queuectl worker start &                # background
sleep 2 && kill -9 $!                  # SIGKILL worker
sleep 20
queuectl worker start                  # should recover job

# Tests
python -m unittest discover -s tests -v
```

---

## Automated tests

```powershell
cd c:\Users\shlok\Desktop\QueueCTL

# Run all tests (~90 seconds)
python -m unittest discover -s tests -v

# Individual test files
python -m unittest tests.test_grading_scenarios -v
python tests/test_restart_survival.py
python tests/test_interface_contract.py
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `queuectl` not found | Not on PATH after pip install | Use `python -m queuectl.cli` |
| JSON parse error on enqueue (PowerShell) | PowerShell strips quotes | Use `$job = '{"id":"x",...}'` variable |
| Jobs disappear instantly | Orphan worker from previous run | `python -m queuectl.cli worker stop`, delete `.queuectl/`, restart |
| `list --json` returns `[]` but job was enqueued | Stray worker claimed it | Kill all python worker processes, reset `.queuectl/` |
| Worker won't stop on Windows | SIGTERM unreliable cross-terminal | Stop files (`.stop`) are used automatically — wait ~1s |
| Database locked error | Two processes writing simultaneously | Should auto-resolve via `busy_timeout=5000`; if persistent, delete `.queuectl/` |
| Multiprocessing orphans after `--count N` | Child processes survive parent kill | `python -m queuectl.cli worker stop` or restart terminal |

---

## Key numbers to remember (for interview)

| Setting | Value | File |
|---------|-------|------|
| Lease duration | 15 seconds | `queue_ops.py` → `LEASE_SECONDS` |
| Heartbeat interval | 5 seconds | `worker.py` → `HEARTBEAT_INTERVAL_SECONDS` |
| Poll interval | 1 second | `worker.py` → `POLL_INTERVAL_SECONDS` |
| Worst-case crash recovery | **16 seconds** | 15s lease + 1s poll |
| Default max_retries | 3 | `config.py` |
| Default backoff_base | 2.0 | `config.py` |
| Backoff formula | `base ^ attempts` seconds | `queue_ops.py` → `fail_job()` |

---

## Related documents

- **README.md** — short setup + command reference (for GitHub visitors)
- **DECISIONS.md** — design rationale with line references (required for grading)
