import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL DEFAULT '',   -- raw JD text; resume-screening pipeline reads this directly
    jd_filename TEXT,
    jd_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | active
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    is_mandatory INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'default'   -- default | ai | custom
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    resume_path TEXT,             -- filename of the matched CV inside the job's candidates/ folder
    resume_text TEXT,             -- extracted resume text (resume-screening pipeline)
    profile_json TEXT NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'PARSING',   -- PARSING | SCORING | SCORED | ERROR (resume-screening pipeline state)
    error_reason TEXT,
    -- HR's resume-screening decision (distinct from the tracker-imported *_status columns
    -- below, which get overwritten on every tracker re-sync). NULL | 'rejected'. Reversible.
    screening_decision TEXT,
    -- Output of the resume-screening pipeline: mandatory gate result, fitment
    -- score, recommendation, strengths/gaps. NULL means not yet screened.
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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rubrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    criteria_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(job_id, version)
);

CREATE TABLE IF NOT EXISTS criterion_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    rubric_id INTEGER NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    criterion_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    evidence TEXT,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(candidate_id, rubric_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT,
    entity_id INTEGER,
    action TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cs_lookup ON criterion_scores(rubric_id, candidate_id);
CREATE INDEX IF NOT EXISTS idx_cand_job ON candidates(job_id, status);

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
    selected_question_ids TEXT,      -- JSON list of job_questions.id chosen by the recruiter for this trigger
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

-- One row per (candidate, round). Upserted whenever a round produces a fresh
-- evaluation — e.g. the HR screening chat finishing runs an LLM pass and
-- writes its result here. `score` is that round's own opinion, not a global
-- fitment number; rounds a pipeline hasn't run yet (e.g. resume_screening
-- until that pipeline ships) simply have no row, and the UI shows it empty.
CREATE TABLE IF NOT EXISTS round_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    round TEXT NOT NULL,             -- resume_screening | hr_screening | l1 | l2 | l3 | pre_offer
    score INTEGER,
    summary TEXT,
    key_highlights_json TEXT,        -- JSON list of strings
    flags_json TEXT,                 -- JSON list of {"type": "red"|"green", "detail": "..."}
    session_id INTEGER REFERENCES screening_sessions(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(candidate_id, round)
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
# NOTE: only covers columns added before this merge. If your local db/*.db
# predates the resume-screening pipeline tables (rubrics, criterion_scores,
# audit_log, jobs.jd_text, candidates.resume_text/status/error_reason),
# delete the file and let init_db() recreate it fresh rather than relying on
# a migration path for it — not worth building out for a hackathon SQLite file.
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
    "screening_decision": "TEXT",
}
_JOB_QUESTION_COLUMNS = {"source": "TEXT NOT NULL DEFAULT 'default'"}
_SCREENING_SESSION_COLUMNS = {"selected_question_ids": "TEXT"}

# Generic HR screening questions every job should have regardless of its JD —
# inserted for new jobs at creation time, and backfilled onto any job that's
# missing them (by exact text match, so re-running this is a no-op).
DEFAULT_HR_QUESTIONS = [
    "Are you comfortable working from Mumbai (or relocating)?",
    "Why are you looking for a change?",
    "Why are you interested in joining Seclore?",
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in (
        ("jobs", _JOB_COLUMNS),
        ("candidates", _CANDIDATE_COLUMNS),
        ("job_questions", _JOB_QUESTION_COLUMNS),
        ("screening_sessions", _SCREENING_SESSION_COLUMNS),
    ):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    # NULLs are always distinct in a unique index, so rows without an
    # external_id (e.g. seeded demo candidates) never collide with each other.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_job_external ON candidates(job_id, external_id)"
    )
    _backfill_default_hr_questions(conn)


def _backfill_default_hr_questions(conn: sqlite3.Connection) -> None:
    job_ids = [row["id"] for row in conn.execute("SELECT id FROM jobs")]
    for job_id in job_ids:
        existing_texts = {
            row["question_text"]
            for row in conn.execute("SELECT question_text FROM job_questions WHERE job_id = ?", (job_id,))
        }
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM job_questions WHERE job_id = ?", (job_id,)
        ).fetchone()["m"]
        next_index = max_order + 1
        for question in DEFAULT_HR_QUESTIONS:
            if question in existing_texts:
                continue
            conn.execute(
                """INSERT INTO job_questions (job_id, question_text, order_index, is_mandatory, source)
                   VALUES (?, ?, ?, 1, 'default')""",
                (job_id, question, next_index),
            )
            next_index += 1


def init_db() -> None:
    """Create tables if they don't exist yet, migrate schema, then seed demo data if empty."""
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()

    from app.seed import seed_demo_data

    seed_demo_data()
