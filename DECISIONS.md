# Design Decisions

Answers to the five grading questions will be added in Phase 13.

## DLQ retry resets attempts

`dlq retry` sets `attempts=0` because a human operator is explicitly deciding the
underlying failure is resolved. The job receives a full fresh retry budget, not
a continuation of the previous failure streak.

## Crash recovery worst-case delay

Worst-case recovery time = `LEASE_SECONDS + poll_interval` = 15s + 1s = **16 seconds**.
After a worker is SIGKILLed mid-job, the job stays `processing` until its lease
expires, then the next worker poll reclaims it via the stale-lease clause in the
claim query.

## Worker stop design (rejected alternatives)

We use PID files under `.queuectl/workers/` plus `SIGTERM` for `worker stop`.
Rejected alternatives:

- **Unix domain control socket** — unnecessary complexity and failure surface for
  this scale; requires a separate listener process and socket lifecycle management.
- **DB-polled "stop requested" flag** — adds latency equal to the worker poll
  interval (~1s) whereas OS signals are effectively instant on Unix. We still
  write per-worker `.stop` files alongside `SIGTERM` because Windows does not
  reliably deliver signals across terminal sessions; workers check the file each
  poll iteration as a portable fallback (max ~1s latency, same as poll interval).
