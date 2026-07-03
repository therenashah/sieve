import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | active
    jd_filename TEXT,
    jd_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    is_mandatory INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    profile_json TEXT NOT NULL DEFAULT '{}',
    -- Output of the (not-yet-built) resume-screening pipeline: mandatory gate
    -- result, fitment score, recommendation, strengths/gaps. NULL means the
    -- candidate hasn't been through that pipeline yet.
    screening_result_json TEXT,
    -- Fields imported from the recruiter's candidate tracker (CSV/XLSX upload).
    external_id TEXT,             -- Candidate ID from the tracker (also used as the CV filename prefix)
    match_score INTEGER,          -- Match Score (AI Based)
    overall_status TEXT,
    recruiter TEXT,
    tags TEXT,
    application_date TEXT,
    source_type TEXT,
    source_name TEXT,
    ownership_status TEXT,
    shortlisting_status TEXT,
    resume_screening_status TEXT,
    l1_status TEXT,
    l2_status TEXT,
    l3_status TEXT,
    pre_offer_status TEXT,
    resume_path TEXT,             -- filename of the matched CV inside the job's candidates/ folder
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS screening_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',           -- active | completed | expired
    phase TEXT NOT NULL DEFAULT 'GREETING',          -- GREETING | MANDATORY | PROFILE_FOLLOWUP | SECLORE_QA | ENDED
    current_question_index INTEGER NOT NULL DEFAULT 0,
    pending_question_text TEXT,
    profile_followup_count INTEGER NOT NULL DEFAULT 0,
    seclore_qa_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    summary TEXT,
    key_highlights TEXT
);

CREATE TABLE IF NOT EXISTS screening_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES screening_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                              -- user | assistant
    content TEXT NOT NULL,
    phase TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS screening_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES screening_sessions(id) ON DELETE CASCADE,
    question_id INTEGER REFERENCES job_questions(id),
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL,                     -- mandatory | profile_followup
    answer_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recruiter_sessions (
    token TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    term_freqs TEXT NOT NULL,          -- JSON {token: count}, used for lexical retrieval
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


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


# Columns added after the initial release of a table — CREATE TABLE IF NOT
# EXISTS won't retrofit these onto a database file that predates them, so we
# ALTER TABLE any that are missing on every startup (idempotent, cheap).
_JOB_COLUMNS = {"status": "TEXT NOT NULL DEFAULT 'draft'", "jd_filename": "TEXT", "jd_path": "TEXT"}
_CANDIDATE_COLUMNS = {
    "external_id": "TEXT",
    "match_score": "INTEGER",
    "overall_status": "TEXT",
    "recruiter": "TEXT",
    "tags": "TEXT",
    "application_date": "TEXT",
    "source_type": "TEXT",
    "source_name": "TEXT",
    "ownership_status": "TEXT",
    "shortlisting_status": "TEXT",
    "resume_screening_status": "TEXT",
    "l1_status": "TEXT",
    "l2_status": "TEXT",
    "l3_status": "TEXT",
    "pre_offer_status": "TEXT",
    "resume_path": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in (("jobs", _JOB_COLUMNS), ("candidates", _CANDIDATE_COLUMNS)):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    # NULLs are always distinct in a unique index, so rows without an
    # external_id (e.g. seeded demo candidates) never collide with each other.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_job_external ON candidates(job_id, external_id)"
    )


def init_db() -> None:
    """Create tables if they don't exist yet, migrate schema, then seed demo data if empty."""
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()

    from app.seed import seed_demo_data

    seed_demo_data()
