"""
history_service.py — A small SQLite table that remembers past generation
runs (when, how many records, what config, what quality score) so the
dashboard can show "Recent generation information" even after a browser
refresh. This does NOT store the lease records themselves — those live
in generated_datasets/ as CSV/JSON — only metadata about each run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from config import Config


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the generation_history table if it doesn't already exist.
    Safe to call on every app startup.
    """
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TEXT NOT NULL,
                record_count    INTEGER NOT NULL,
                quality_score   REAL,
                config_json     TEXT,
                csv_path        TEXT,
                json_path       TEXT
            )
            """
        )
        conn.commit()


def record_generation(
    record_count: int,
    config: dict,
    quality_score: float,
    csv_path: Optional[str],
    json_path: Optional[str],
) -> int:
    """Insert one row for a completed generation run. Returns the new row id."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO generation_history
                (created_at, record_count, quality_score, config_json, csv_path, json_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                record_count,
                quality_score,
                json.dumps(config),
                csv_path,
                json_path,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_recent_generations(limit: int = 10) -> list:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, record_count, quality_score, config_json
            FROM generation_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    results = []
    for row in rows:
        try:
            cfg = json.loads(row["config_json"]) if row["config_json"] else {}
        except (TypeError, json.JSONDecodeError):
            cfg = {}
        results.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "record_count": row["record_count"],
                "quality_score": row["quality_score"],
                "config": cfg,
            }
        )
    return results
