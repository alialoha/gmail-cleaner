"""SQLite run history for scans, findings, and confirmed actions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gmail_cleaner.paths import db_path, ensure_layout


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        ensure_layout()
        self.path = path or db_path()
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary_json TEXT
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    sender TEXT,
                    query TEXT,
                    message_count INTEGER NOT NULL,
                    est_bytes INTEGER NOT NULL,
                    sample_ids_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    permanent INTEGER NOT NULL DEFAULT 0,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    detail_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def start_run(self, account_id: str, mode: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, account_id, mode, status, started_at)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (run_id, account_id, mode, _utc_now()),
            )
            conn.execute(
                """
                INSERT INTO events (run_id, level, message, created_at)
                VALUES (?, 'info', ?, ?)
                """,
                (run_id, f"Started {mode} for {account_id}", _utc_now()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        summary: dict[str, Any] | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, summary_json = ?
                WHERE run_id = ?
                """,
                (status, _utc_now(), json.dumps(summary or {}), run_id),
            )
            conn.execute(
                """
                INSERT INTO events (run_id, level, message, created_at)
                VALUES (?, 'info', ?, ?)
                """,
                (run_id, f"Finished with status={status}", _utc_now()),
            )

    def add_finding(
        self,
        run_id: str,
        *,
        bucket: str,
        sender: str | None,
        query: str | None,
        message_count: int,
        est_bytes: int,
        sample_ids: list[str] | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO findings (
                    run_id, bucket, sender, query, message_count, est_bytes, sample_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    bucket,
                    sender,
                    query,
                    message_count,
                    est_bytes,
                    json.dumps(sample_ids or []),
                ),
            )

    def record_action(
        self,
        run_id: str,
        *,
        action: str,
        message_count: int,
        permanent: bool,
        confirmed: bool,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO actions (
                    run_id, action, message_count, permanent, confirmed, created_at, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    action,
                    message_count,
                    int(permanent),
                    int(confirmed),
                    _utc_now(),
                    json.dumps(detail or {}),
                ),
            )

    def log_event(self, message: str, *, run_id: str | None = None, level: str = "info") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO events (run_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, level, message, _utc_now()),
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT run_id, account_id, mode, status, started_at, finished_at, summary_json
                FROM runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            findings = conn.execute(
                "SELECT * FROM findings WHERE run_id = ? ORDER BY est_bytes DESC",
                (run_id,),
            ).fetchall()
            actions = conn.execute(
                "SELECT * FROM actions WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
            events = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return {
            **dict(row),
            "findings": [dict(f) for f in findings],
            "actions": [dict(a) for a in actions],
            "events": [dict(e) for e in events],
        }
