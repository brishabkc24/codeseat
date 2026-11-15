"""Durable storage for CodeSeat: teachers, their sessions and their classes.

Three small tables. A class's live state (its lesson, the students, their code)
is one JSON document per class, so the classroom in rooms.py stays the model and
this module only copies it in and out. Nothing here knows about HTTP.

Two databases are supported behind the same class: a SQLite file, for running
on one's own computer and for tests, and Postgres, for a host whose disk does
not survive a restart. The SQL is written once and is valid for both.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# "rows" and "cols" are quoted because ROWS is a word of its own in Postgres.
SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS classes (
    code TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    "rows" INTEGER NOT NULL,
    "cols" INTEGER NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS classes_by_teacher ON classes (teacher_id, created_at);
CREATE INDEX IF NOT EXISTS sessions_by_teacher ON sessions (teacher_id)
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


def _teacher(row: Mapping | None) -> TeacherRecord | None:
    if row is None:
        return None
    return TeacherRecord(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
    )


def _class(row: Mapping | None) -> ClassRecord | None:
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
    """What the server asks of its database. A subclass supplies the connection.

    Calls are serialised with a lock: the server reaches the database from the
    event loop (sockets) and from worker threads (the REST handlers, saving).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ---- supplied by the database: run one statement, with ? for each value

    def _run(self, sql: str, values: tuple = ()):
        """Runs the statement and returns its cursor. Called with the lock held."""
        raise NotImplementedError

    def _is_duplicate(self, error: Exception) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    # ---- shared

    def _create_tables(self) -> None:
        with self._lock:
            for statement in SCHEMA.split(";"):
                self._run(statement)

    def _one(self, sql: str, values: tuple = ()) -> Mapping | None:
        with self._lock:
            return self._run(sql, values).fetchone()

    def _all(self, sql: str, values: tuple = ()) -> list[Mapping]:
        with self._lock:
            return self._run(sql, values).fetchall()

    def _change(self, sql: str, values: tuple = ()) -> int:
        """Runs a statement that changes rows and returns how many it changed."""
        with self._lock:
            return self._run(sql, values).rowcount

    # ---------------------------------------------------------------- teachers

    def add_teacher(self, teacher: TeacherRecord) -> None:
        try:
            self._change(
                "INSERT INTO teachers (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (teacher.id, teacher.name, teacher.email, teacher.password_hash, teacher.created_at),
            )
        except Exception as error:
            if self._is_duplicate(error):
                raise EmailTaken() from error
            raise

    def teacher_by_email(self, email: str) -> TeacherRecord | None:
        return _teacher(self._one("SELECT * FROM teachers WHERE email = ?", (email,)))

    def teacher_by_id(self, teacher_id: str) -> TeacherRecord | None:
        return _teacher(self._one("SELECT * FROM teachers WHERE id = ?", (teacher_id,)))

    # ---------------------------------------------------------------- sessions

    def add_session(self, token_hash: str, teacher_id: str, created_at: float, expires_at: float) -> None:
        self._change(
            "INSERT INTO sessions (token_hash, teacher_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, teacher_id, created_at, expires_at),
        )

    def teacher_for_session(self, token_hash: str, now: float) -> TeacherRecord | None:
        return _teacher(
            self._one(
                "SELECT teachers.* FROM sessions JOIN teachers ON teachers.id = sessions.teacher_id"
                " WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (token_hash, now),
            )
        )

    def delete_session(self, token_hash: str) -> None:
        self._change("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_expired_sessions(self, now: float) -> None:
        self._change("DELETE FROM sessions WHERE expires_at <= ?", (now,))

    # ---------------------------------------------------------------- classes

    def save_class(self, record: ClassRecord) -> None:
        self._change(
            'INSERT INTO classes (code, teacher_id, title, "rows", "cols", created_at, updated_at, state)'
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            ' ON CONFLICT (code) DO UPDATE SET title = excluded.title, "rows" = excluded."rows",'
            ' "cols" = excluded."cols", updated_at = excluded.updated_at, state = excluded.state',
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
        return _class(self._one("SELECT * FROM classes WHERE code = ?", (code,)))

    def classes_for_teacher(self, teacher_id: str) -> list[ClassRecord]:
        rows = self._all("SELECT * FROM classes WHERE teacher_id = ? ORDER BY created_at DESC", (teacher_id,))
        return [record for record in map(_class, rows) if record is not None]

    def class_exists(self, code: str) -> bool:
        return self._one("SELECT 1 AS found FROM classes WHERE code = ?", (code,)) is not None

    def delete_class(self, code: str) -> bool:
        return self._change("DELETE FROM classes WHERE code = ?", (code,)) > 0


class SqliteStorage(Storage):
    """One SQLite file, or ":memory:" for tests."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        in_memory = str(path) == ":memory:"
        if not in_memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            if not in_memory:
                self._db.execute("PRAGMA journal_mode = WAL")
                self._db.execute("PRAGMA synchronous = NORMAL")
        self._create_tables()

    def _run(self, sql: str, values: tuple = ()):
        return self._db.execute(sql, values)

    def _is_duplicate(self, error: Exception) -> bool:
        return isinstance(error, sqlite3.IntegrityError)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class PostgresStorage(Storage):
    """A Postgres database, named by a postgres:// address.

    One connection, opened when first needed. Hosted databases close a
    connection that has sat idle (and some go to sleep), so a statement that
    finds the connection gone is run once more on a fresh one.
    """

    def __init__(self, url: str) -> None:
        super().__init__()
        import psycopg  # needed only where Postgres is used
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self._row_factory = dict_row
        self._url = url
        self._db = None
        self._create_tables()

    def _connect(self) -> None:
        self._db = self._psycopg.connect(
            self._url,
            autocommit=True,
            row_factory=self._row_factory,
            prepare_threshold=None,  # connection poolers in front of the database cannot keep prepared statements
            connect_timeout=20,
        )

    def _run(self, sql: str, values: tuple = ()):
        gone = (self._psycopg.OperationalError, self._psycopg.InterfaceError)
        for attempt in (1, 2):
            try:
                if self._db is None or self._db.closed:
                    self._connect()
                return self._db.execute(sql.replace("?", "%s"), values)
            except gone:
                self._drop()
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def _drop(self) -> None:
        try:
            if self._db is not None:
                self._db.close()
        except Exception:
            pass
        self._db = None

    def _is_duplicate(self, error: Exception) -> bool:
        return isinstance(error, self._psycopg.errors.UniqueViolation)

    def close(self) -> None:
        with self._lock:
            self._drop()


def open_storage(target: str | Path) -> Storage:
    """A postgres:// or postgresql:// address opens Postgres; anything else is a SQLite file."""
    if isinstance(target, str) and target.startswith(("postgres://", "postgresql://")):
        return PostgresStorage(target)
    return SqliteStorage(target)
