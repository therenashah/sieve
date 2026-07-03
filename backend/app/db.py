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

-- The rounds configured for a job, in pipeline order. resume_screening and
-- hr_screening are seeded as builtins (is_builtin=1, can't be deleted) since
-- they're wired to dedicated pipelines; anything else is an optional round the
-- recruiter added from a template (or fully custom), most of them AI-interview
-- rounds whose ai_config_json drives what a future AI interviewer bot gets
-- told/does — this table is that bot's config source, not just UI decoration.
CREATE TABLE IF NOT EXISTS job_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    round_key TEXT NOT NULL,         -- stable key, matches round_results.round
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    is_ai_based INTEGER NOT NULL DEFAULT 0,
    ai_config_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(job_id, round_key)
);

-- One AI interview per (candidate, round) trigger. Mirrors screening_sessions but
-- for the video/audio AI interview round: the recruiter triggers it, the candidate
-- schedules a slot within the invite window, then joins the tokenized room. The
-- config_json is a snapshot of the round's RoundAIConfig at trigger time, so the
-- interviewer reads exactly what the recruiter set even if the round is edited later.
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    round_key TEXT NOT NULL,           -- matches job_rounds.round_key / round_results.round
    status TEXT NOT NULL DEFAULT 'invited',   -- invited | scheduled | in_progress | completed | expired
    phase TEXT NOT NULL DEFAULT 'INTRO',      -- INTRO | INTERVIEW | WRAPUP | ENDED
    config_json TEXT NOT NULL DEFAULT '{}',   -- snapshot of RoundAIConfig
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    plan_json TEXT,                    -- generated interview plan (sections/questions)
    current_index INTEGER NOT NULL DEFAULT 0, -- index into the plan's question list
    followups_used INTEGER NOT NULL DEFAULT 0,-- follow-ups asked on the current question
    scheduled_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,          -- invite/scheduling window end
    started_at TEXT,
    ended_at TEXT,
    completed_at TEXT,
    recording_path TEXT,
    summary TEXT,
    score INTEGER,
    scorecard_json TEXT                -- full evaluation detail (competencies, recommendation)
);

CREATE TABLE IF NOT EXISTS interview_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                -- assistant | candidate
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'talk', -- intro | question | followup | repeat | answer | wrapup | closing
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Lightweight proctoring/telemetry trail (tab switches, camera off, etc.).
CREATE TABLE IF NOT EXISTS interview_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interview_cand ON interview_sessions(job_id, candidate_id, round_key);

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

# The two rounds every job pipeline has by default — seeded for new jobs and
# backfilled onto any job created before job_rounds existed.
BUILTIN_ROUNDS = [
    {
        "round_key": "resume_screening",
        "name": "Resume Screening",
        "description": "AI mandatory-gate check and fitment scoring against the JD-derived rubric.",
    },
    {
        "round_key": "hr_screening",
        "name": "HR Screening",
        "description": "Conversational HR screening chat covering logistics, background, and culture fit.",
    },
]

# Catalog of optional rounds a recruiter can add from the round management UI.
# "custom" has no fixed round_key — the endpoint mints one (custom_1, custom_2, ...).
ROUND_TEMPLATES = [
    {
        "key": "l1_interview",
        "name": "L1 Interview",
        "description": "First technical/managerial round assessing core competency fit.",
    },
    {
        "key": "l2_interview",
        "name": "L2 Interview",
        "description": "Second-level interview, typically a deeper technical or leadership assessment.",
    },
    {
        "key": "technical_interview_1",
        "name": "Technical Interview 1",
        "description": "Focused technical assessment — coding, system design, or domain expertise.",
    },
    {
        "key": "technical_interview_2",
        "name": "Technical Interview 2",
        "description": "A second technical round, often deeper or with a different panel.",
    },
    {
        "key": "custom",
        "name": "Custom Round",
        "description": "Define your own round from scratch.",
    },
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
    _backfill_builtin_rounds(conn)


def _backfill_builtin_rounds(conn: sqlite3.Connection) -> None:
    job_ids = [row["id"] for row in conn.execute("SELECT id FROM jobs")]
    for job_id in job_ids:
        existing = {
            row["round_key"] for row in conn.execute("SELECT round_key FROM job_rounds WHERE job_id = ?", (job_id,))
        }
        for index, round_def in enumerate(BUILTIN_ROUNDS):
            if round_def["round_key"] in existing:
                continue
            conn.execute(
                """INSERT INTO job_rounds (job_id, round_key, name, description, order_index, is_builtin)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (job_id, round_def["round_key"], round_def["name"], round_def["description"], index),
            )


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
