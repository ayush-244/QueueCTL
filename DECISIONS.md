# Design Decisions

Answers to the five grading questions will be added in Phase 13.

## DLQ retry resets attempts

`dlq retry` sets `attempts=0` because a human operator is explicitly deciding the
underlying failure is resolved. The job receives a full fresh retry budget, not
a continuation of the previous failure streak.
