# QueueCTL

A CLI-based background job queue with multi-process workers, exponential backoff retries, lease-based crash recovery, and a Dead Letter Queue (DLQ). Built with **Python 3.11+**, **Click**, and **SQLite** (stdlib only — no ORM, no Redis).

## Setup

```bash
git clone <your-repo-url>
cd QueueCTL
pip install -e .
queuectl --help
```

If `queuectl` is not on your `PATH` after install:

```bash
python -m queuectl.cli --help
```

Runtime data (database, worker PID files) is stored in `.queuectl/` in the current working directory.

## Quick start

```bash
# Enqueue jobs
queuectl enqueue '{"id":"job1","command":"echo hello"}'
queuectl enqueue '{"id":"job2","command":"sleep 2"}'

# Start workers in the foreground (blocks until stopped)
queuectl worker start
# Or multiple worker processes:
queuectl worker start --count 3

# In another terminal:
queuectl status
queuectl list --state pending
queuectl list --state completed --json
queuectl worker stop
```

## Command reference

### Enqueue

```bash
queuectl enqueue '{"id":"job1","command":"echo hello"}'
```

Prints the created job as JSON. Optional fields: `max_retries`, `backoff_base`. Config defaults are **snapshotted onto the job row** at enqueue time (later config changes do not affect existing jobs).

**Example output:**

```json
{"id": "job1", "command": "echo hello", "state": "pending", "attempts": 0, "max_retries": 3, "backoff_base": 2.0, ...}
```

### Workers

```bash
queuectl worker start              # one worker, foreground
queuectl worker start --count 5    # five OS processes, parent blocks
queuectl worker stop               # graceful stop from any terminal
```

`worker start` blocks in the foreground. `Ctrl+C` / `SIGTERM` finishes the current job, then exits. `SIGKILL` simulates a crash — jobs are recovered via lease expiry (see DECISIONS.md).

### Status & list

```bash
queuectl status
queuectl list --state pending
queuectl list --state processing
queuectl list --state completed --json   # stdout is ONLY a JSON array
```

**Example `status` output:**

```
Job counts:
  pending: 2
  processing: 1
  completed: 5
  failed: 0
  dead: 0
Live workers: 2
```

### Dead Letter Queue

```bash
queuectl dlq list
queuectl dlq list --json
queuectl dlq retry job1
```

`dlq retry` resets `attempts` to 0 and moves the job back to `pending`.

### Configuration

```bash
queuectl config set max-retries 5
queuectl config set backoff-base 3
```

Affects **newly enqueued** jobs only. Existing jobs keep the `max_retries` / `backoff_base` values stored on their row.

## Architecture

```
enqueue ──► SQLite (jobs table, WAL mode)
                │
                ▼
         worker start (N OS processes)
                │
                ▼
    ┌─── claim (BEGIN IMMEDIATE + atomic UPDATE) ───┐
    │  picks: pending | failed (backoff elapsed)    │
    │         | processing (stale lease)            │
    └───────────────────┬───────────────────────────┘
                        ▼
              subprocess.run(command, shell=True)
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
      completed      failed        dead (DLQ)
                   (retry w/      after max_retries
                    backoff)
```

**Crash recovery:** While a job runs, a heartbeat thread renews `lease_expires_at` every ~5s (default lease = 15s). If a worker is `SIGKILL`ed, the lease expires and the next worker reclaims the job via the stale-lease clause in the claim query. Worst-case recovery: **16 seconds** (15s lease + 1s poll).

**Concurrency safety:** Job claiming is a single `UPDATE ... RETURNING` inside `BEGIN IMMEDIATE`. SQLite serializes writers at the file level, so two OS processes cannot both claim the same row.

## Running tests

```bash
# All grading scenarios (subprocess-driven, uses real CLI)
python -m unittest discover -s tests -v

# Or individual modules:
python -m unittest tests.test_grading_scenarios -v
python tests/test_restart_survival.py
python tests/test_interface_contract.py
```

Scenarios covered:

1. Basic job completes
2. Failing job retries with backoff → DLQ
3. Many jobs across multiple workers — exactly-once execution
4. `SIGKILL` mid-job → recovers within worst-case bound
5. Full restart survival

## Demo recording

**[QueueCTL CLI demo](https://drive.google.com/file/d/12201XqJnP4VHdIpwga4HEmUPjwELvLoG/view?usp=drive_link)** — Screen recording of the queue system in action.

The demo shows: enqueue (including a failing job), multi-worker execution, `status`/`list` output, SIGKILL recovery, `worker stop`, and DLQ retry.

## Project layout

```
queuectl/
  cli.py          # Click entrypoint
  db.py           # SQLite + WAL + schema
  models.py       # Job dataclass, state constants
  queue_ops.py    # enqueue, claim, complete, fail, DLQ
  worker.py       # worker loop, heartbeat, signal handling
  config.py       # persisted configuration
  pidfiles.py     # worker PID / stop files
tests/            # subprocess-driven test suite
DECISIONS.md      # design rationale (required for grading)
PROJECT_GUIDE.md  # full project guide — every file + manual testing
```

> **For a complete explanation of every file and step-by-step manual testing commands, see [PROJECT_GUIDE.md](PROJECT_GUIDE.md).**

## License

MIT (or your choice)
