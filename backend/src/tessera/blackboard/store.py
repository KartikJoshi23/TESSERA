"""Append-only event store on SQLite. Events are never updated or deleted."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    usage      TEXT,
    latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_case ON events (case_id, seq);
"""


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int | None = None
    case_id: str
    ts: datetime
    actor: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, int] | None = None
    latency_ms: int | None = None


class EventStore:
    """One SQLite file per run. Use ``":memory:"`` in tests."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, event: Event) -> Event:
        row = (
            event.case_id,
            event.ts.isoformat(),
            event.actor,
            event.type,
            json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
            json.dumps(event.usage) if event.usage is not None else None,
            event.latency_ms,
        )
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO events (case_id, ts, actor, type, payload, usage, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._conn.commit()
        return event.model_copy(update={"seq": cursor.lastrowid})

    def read(self, case_id: str) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, case_id, ts, actor, type, payload, usage, latency_ms "
                "FROM events WHERE case_id = ? ORDER BY seq",
                (case_id,),
            ).fetchall()
        return [
            Event(
                seq=seq,
                case_id=cid,
                ts=datetime.fromisoformat(ts),
                actor=actor,
                type=kind,
                payload=json.loads(payload),
                usage=json.loads(usage) if usage else None,
                latency_ms=latency,
            )
            for seq, cid, ts, actor, kind, payload, usage, latency in rows
        ]

    def case_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT case_id, MIN(seq) FROM events GROUP BY case_id ORDER BY MIN(seq)"
            ).fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
