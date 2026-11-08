"""Durable storage for CodeSeat: teachers, their sessions and their classes, in SQLite.

Three small tables. A class's live state (its lesson, the students, their code)
is one JSON document per class, so the classroom in rooms.py stays the model and
this module only copies it in and out. Nothing here knows about HTTP.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS classes (
    code TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS classes_by_teacher ON classes (teacher_id, created_at);
CREATE INDEX IF NOT EXISTS sessions_by_teacher ON sessions (teacher_id);
"""


class EmailTaken(Exception):
    """A teacher account with this email already exists."""


@dataclass
class TeacherRecord:
    id: str
    name: str
    email: str
    password_hash: str
    created_at: float


@dataclass
class ClassRecord:
    code: str
    teacher_id: str
    title: str
    rows: int
    cols: int
    created_at: float
    updated_at: float
    state: dict = field(default_factory=dict)


def _teacher(row: sqlite3.Row | None) -> TeacherRecord | None:
    if row is None:
        return None
    return TeacherRecord(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def _class(row: sqlite3.Row | None) -> ClassRecord | None:
    if row is None:
        return None
    return ClassRecord(
        code=row["code"],
        teacher_id=row["teacher_id"],
        title=row["title"],
        rows=row["rows"],
        cols=row["cols"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        state=json.loads(row["state"]),
    )


class Storage:
    """One SQLite file, or ":memory:" for tests.

    Calls are serialised with a lock: the server reaches the database from the
    event loop (sockets) and from worker threads (the REST handlers).
    """

    def __init__(self, path: str | Path) -> None:
        in_memory = str(path) == ":memory:"
        if not in_memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            if not in_memory:
                self._db.execute("PRAGMA journal_mode = WAL")
                self._db.execute("PRAGMA synchronous = NORMAL")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---------------------------------------------------------------- teachers

    def add_teacher(self, teacher: TeacherRecord) -> None:
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO teachers (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (teacher.id, teacher.name, teacher.email, teacher.password_hash, teacher.created_at),
                )
            except sqlite3.IntegrityError as error:
                raise EmailTaken() from error

    def teacher_by_email(self, email: str) -> TeacherRecord | None:
        with self._lock:
            return _teacher(self._db.execute("SELECT * FROM teachers WHERE email = ?", (email,)).fetchone())

    def teacher_by_id(self, teacher_id: str) -> TeacherRecord | None:
        with self._lock:
            return _teacher(self._db.execute("SELECT * FROM teachers WHERE id = ?", (teacher_id,)).fetchone())

    # ---------------------------------------------------------------- sessions

    def add_session(self, token_hash: str, teacher_id: str, created_at: float, expires_at: float) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (token_hash, teacher_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash, teacher_id, created_at, expires_at),
            )

    def teacher_for_session(self, token_hash: str, now: float) -> TeacherRecord | None:
        with self._lock:
            row = self._db.execute(
                "SELECT teachers.* FROM sessions JOIN teachers ON teachers.id = sessions.teacher_id"
                " WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (token_hash, now),
            ).fetchone()
            return _teacher(row)

    def delete_session(self, token_hash: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_expired_sessions(self, now: float) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))

    # ---------------------------------------------------------------- classes

    def save_class(self, record: ClassRecord) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO classes (code, teacher_id, title, rows, cols, created_at, updated_at, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(code) DO UPDATE SET title = excluded.title, rows = excluded.rows,"
                " cols = excluded.cols, updated_at = excluded.updated_at, state = excluded.state",
                (
                    record.code,
                    record.teacher_id,
                    record.title,
                    record.rows,
                    record.cols,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.state, separators=(",", ":")),
                ),
            )

    def load_class(self, code: str) -> ClassRecord | None:
        with self._lock:
            return _class(self._db.execute("SELECT * FROM classes WHERE code = ?", (code,)).fetchone())

    def classes_for_teacher(self, teacher_id: str) -> list[ClassRecord]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM classes WHERE teacher_id = ? ORDER BY created_at DESC", (teacher_id,)
            ).fetchall()
        return [record for record in map(_class, rows) if record is not None]

    def class_exists(self, code: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM classes WHERE code = ?", (code,)).fetchone() is not None

    def delete_class(self, code: str) -> bool:
        with self._lock:
            return self._db.execute("DELETE FROM classes WHERE code = ?", (code,)).rowcount > 0
