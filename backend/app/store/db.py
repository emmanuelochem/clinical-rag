"""SQLite store for structured clinical data, the document registry and the audit log."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY, mrn TEXT UNIQUE, first_name TEXT, last_name TEXT, sex TEXT,
    birth_date TEXT, blood_type TEXT, phone TEXT, address TEXT, primary_provider TEXT,
    synthetic INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    date TEXT, type TEXT, reason TEXT, provider TEXT, department TEXT
);
CREATE TABLE IF NOT EXISTS conditions (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    code TEXT, display TEXT, onset_date TEXT, abatement_date TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id TEXT, date TEXT, category TEXT, code TEXT, name TEXT, value REAL, unit TEXT,
    ref_low REAL, ref_high REAL, interpretation TEXT
);
CREATE INDEX IF NOT EXISTS obs_patient_code ON observations(patient_id, code, date);
CREATE TABLE IF NOT EXISTS medications (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    name TEXT, dose TEXT, frequency TEXT, start_date TEXT, end_date TEXT, status TEXT, indication TEXT
);
CREATE TABLE IF NOT EXISTS allergies (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    substance TEXT, reaction TEXT, severity TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id TEXT, date TEXT, type TEXT, author TEXT, text TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, title TEXT, source TEXT, mime TEXT, size_bytes INTEGER, status TEXT,
    error TEXT, num_chunks INTEGER DEFAULT 0, created_at TEXT, file_path TEXT,
    scope TEXT DEFAULT 'kb', patient_id TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, patient_id TEXT, detail TEXT
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        with self.tx() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self):
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return [dict(r) for r in self._conn().execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        r = self._conn().execute(sql, params).fetchone()
        return dict(r) if r else None

    def insert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self.tx() as c:
            c.executemany(sql, [tuple(r[k] for k in cols) for r in rows])

    def audit(self, action: str, patient_id: str | None = None, detail: str = "", actor: str = "clinician") -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO audit_log (ts, actor, action, patient_id, detail) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), actor, action, patient_id, detail[:2000]),
            )
