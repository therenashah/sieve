import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """FastAPI dependency: yields a SQLite connection, closed after the request."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist yet. Schema grows as components land."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY, title TEXT, jd_text TEXT NOT NULL,
              status TEXT DEFAULT 'OPEN', created_at TEXT DEFAULT (datetime('now')));

            CREATE TABLE IF NOT EXISTS rubrics (
              id INTEGER PRIMARY KEY, job_id INT NOT NULL,
              version INT NOT NULL, criteria_json TEXT NOT NULL,
              created_at TEXT DEFAULT (datetime('now')),
              UNIQUE(job_id, version));

            CREATE TABLE IF NOT EXISTS candidates (
              id INTEGER PRIMARY KEY, job_id INT NOT NULL,
              name TEXT, email TEXT, resume_path TEXT, resume_text TEXT,
              profile_json TEXT, status TEXT DEFAULT 'PARSING',
              error_reason TEXT, created_at TEXT DEFAULT (datetime('now')));

            CREATE TABLE IF NOT EXISTS criterion_scores (
              id INTEGER PRIMARY KEY, candidate_id INT NOT NULL,
              rubric_id INT NOT NULL, criterion_id TEXT NOT NULL,
              score INT NOT NULL, evidence TEXT, note TEXT,
              created_at TEXT DEFAULT (datetime('now')),
              UNIQUE(candidate_id, rubric_id, criterion_id));

            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY, entity TEXT, entity_id INT,
              action TEXT, payload_json TEXT,
              created_at TEXT DEFAULT (datetime('now')));

            CREATE INDEX IF NOT EXISTS idx_cs_lookup ON criterion_scores(rubric_id, candidate_id);
            CREATE INDEX IF NOT EXISTS idx_cand_job ON candidates(job_id, status);

            -- screening_questions, chat_sessions, messages, stage_scores are
            -- teammate-owned (conversations/ + routes_chat.py) — DDL lives here
            -- when they land it, not implemented as part of this scope.
            """
        )
        conn.commit()
