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
