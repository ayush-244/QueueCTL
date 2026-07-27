"""Job dataclass and state constants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATE_PENDING = "pending"
STATE_PROCESSING = "processing"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_DEAD = "dead"

ALL_STATES = (
    STATE_PENDING,
    STATE_PROCESSING,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_DEAD,
)


@dataclass
class Job:
    id: str
    command: str
    state: str = STATE_PENDING
    attempts: int = 0
    max_retries: int = 3
    backoff_base: float = 2.0
    created_at: str | None = None
    updated_at: str | None = None
    next_retry_at: str | None = None
    lease_expires_at: str | None = None
    worker_pid: int | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "state": self.state,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "backoff_base": self.backoff_base,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_retry_at": self.next_retry_at,
            "lease_expires_at": self.lease_expires_at,
            "worker_pid": self.worker_pid,
            "last_error": self.last_error,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Job:
        return cls(
            id=row["id"],
            command=row["command"],
            state=row["state"],
            attempts=row["attempts"],
            max_retries=row["max_retries"],
            backoff_base=row["backoff_base"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_retry_at=row["next_retry_at"],
            lease_expires_at=row["lease_expires_at"],
            worker_pid=row["worker_pid"],
            last_error=row["last_error"],
        )
