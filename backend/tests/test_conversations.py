import pytest

from app.conversations import engine
from app.db import init_db


@pytest.fixture(autouse=True)
def _init_db():
    init_db()


def test_get_session_raises_for_unknown_token():
    with pytest.raises(engine.SessionNotFoundError):
        engine.get_session("dummy-token")


def test_create_session_returns_token_and_expiry():
    session = engine.create_session(job_id=1, candidate_id=1)
    assert session["token"]
    assert session["expires_at"]

    loaded = engine.get_session(session["token"])
    assert loaded["status"] == "active"
    assert loaded["phase"] == "GREETING"


def test_create_session_raises_for_unknown_job():
    with pytest.raises(engine.SessionNotFoundError):
        engine.create_session(job_id=999, candidate_id=1)


def test_mandatory_questions_seeded():
    # 4 demo-seeded questions + 3 generic defaults backfilled onto every job (see
    # db._backfill_default_hr_questions) = 7.
    questions = engine.get_mandatory_questions(job_id=1)
    assert len(questions) == 7
    assert questions[0]["order_index"] == 0


def test_create_session_blocks_candidate_rejected_at_gate():
    # candidate 3 (Karan Mehta) is seeded with mandatory_gate="REJECTED"
    with pytest.raises(engine.ScreeningGateError):
        engine.create_session(job_id=1, candidate_id=3)


def test_get_candidate_folds_screening_result_into_profile():
    candidate = engine.get_candidate(1)  # Priya Nair — NEEDS_REVIEW, has a gap
    assert candidate["screening_result"]["recommendation"] == "NEEDS_REVIEW"
    assert "resume_screening_result" in candidate["profile"]
    assert candidate["profile"]["resume_screening_result"]["gaps"]
