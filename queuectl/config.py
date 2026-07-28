"""Configuration get/set and defaults."""

from __future__ import annotations

from queuectl.db import get_connection, init_db

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0

CONFIG_MAX_RETRIES = "max_retries"
CONFIG_BACKOFF_BASE = "backoff_base"

CONFIG_KEYS = {
    "max-retries": CONFIG_MAX_RETRIES,
    "backoff-base": CONFIG_BACKOFF_BASE,
}


def _get_config_value(key: str, default: str) -> str:
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def _set_config_value(key: str, value: str) -> None:
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_max_retries() -> int:
    return int(_get_config_value(CONFIG_MAX_RETRIES, str(DEFAULT_MAX_RETRIES)))


def get_backoff_base() -> float:
    return float(_get_config_value(CONFIG_BACKOFF_BASE, str(DEFAULT_BACKOFF_BASE)))


def get_config(cli_key: str) -> str:
    if cli_key not in CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {cli_key}")
    db_key = CONFIG_KEYS[cli_key]
    if cli_key == "max-retries":
        return str(get_max_retries())
    elif cli_key == "backoff-base":
        return str(get_backoff_base())
    return _get_config_value(db_key, "")


def set_config(cli_key: str, value: str) -> None:
    if cli_key not in CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {cli_key}")
    db_key = CONFIG_KEYS[cli_key]
    if cli_key == "max-retries":
        int(value)  # validate
    elif cli_key == "backoff-base":
        float(value)  # validate
    _set_config_value(db_key, value)
