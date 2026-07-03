"""Screening chat state machine.

Phases, in order: GREETING (pre-start only, never has messages) -> MANDATORY ->
PROFILE_FOLLOWUP -> SECLORE_QA -> ENDED. The GREETING->MANDATORY opening turn is a
fixed, deterministic message (see prompts.build_intro_message) — no LLM call, so
the "about Seclore" boilerplate and the exact first question can never drift or be
improvised. Every other phase is bounded (fixed question list, or a config-driven
max turn count), so the conversation can never run open-ended. All LLM calls go
through `app.llm.client`; all persistence goes through the SQLite tables defined
in `app.db`.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.conversations.analyzer import summarize_session
from app.db import get_db
from app.llm import client as llm_client
from app.llm import prompts
from app.rag import retriever


class SessionNotFoundError(Exception):
    pass


class ScreeningGateError(Exception):
    """Raised when trying to trigger a screening chat for a candidate who
    failed the resume-screening pipeline's mandatory gate. Per architecture
    principle #1, a mandatory-condition failure is a hard stop — that
    candidate should never reach a screening chat, let alone fitment scoring.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


def get_job(job_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise SessionNotFoundError(f"job {job_id} not found")
    return dict(row)


def get_candidate(candidate_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if not row:
        raise SessionNotFoundError(f"candidate {candidate_id} not found")
    candidate = dict(row)
    candidate["profile"] = json.loads(candidate["profile_json"])
    candidate["screening_result"] = (
        json.loads(candidate["screening_result_json"]) if candidate["screening_result_json"] else None
    )
    # Fold the resume-screening pipeline's findings (strengths/gaps/unresolved
    # questions) into the profile block the LLM sees — this is what lets the
    # PROFILE_FOLLOWUP phase ask about a flagged gap instead of guessing.
    if candidate["screening_result"]:
        candidate["profile"] = {
            **candidate["profile"],
            "resume_screening_result": {
                k: v
                for k, v in candidate["screening_result"].items()
                if k in {"fitment_score", "recommendation", "strengths", "gaps", "unresolved_questions"}
            },
        }
    return candidate


def get_mandatory_questions(job_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM job_questions WHERE job_id = ? AND is_mandatory = 1
               ORDER BY order_index ASC""",
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_session_questions(session: dict) -> list[dict]:
    """The questions this particular session should ask, in order.

    If the recruiter picked a specific subset when triggering the screening
    link (the trigger modal), use exactly that subset/order. Otherwise fall
    back to every mandatory question on the job (legacy/no-modal path).
    """
    selected_ids = session.get("selected_question_ids")
    if not selected_ids:
        return get_mandatory_questions(session["job_id"])

    ids = json.loads(selected_ids)
    if not ids:
        return get_mandatory_questions(session["job_id"])

    with get_db() as conn:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM job_questions WHERE id IN ({placeholders})", ids
        ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[qid] for qid in ids if qid in by_id]


def _get_session_row(token: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM screening_sessions WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def _save_message(session_id: int, role: str, content: str, phase: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO screening_messages (session_id, role, content, phase) VALUES (?, ?, ?, ?)",
            (session_id, role, content, phase),
        )
        conn.commit()


def _save_answer(session_id: int, question_id: int | None, question_text: str, question_type: str, answer_text: str) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO screening_answers (session_id, question_id, question_text, question_type, answer_text)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, question_id, question_text, question_type, answer_text),
        )
        conn.commit()


def _update_session(session_id: int, **fields) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    with get_db() as conn:
        conn.execute(
            f"UPDATE screening_sessions SET {columns} WHERE id = ?",
            (*fields.values(), session_id),
        )
        conn.commit()


def get_transcript(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, phase, created_at FROM screening_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_answers(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT question_text, question_type, answer_text FROM screening_answers WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _llm_history(session_id: int) -> list[dict]:
    """Bedrock's Messages API requires the history to start with a `user` turn and
    strictly alternate roles. Our bot always speaks first (greeting, follow-up
    prompts, etc.), so the stored transcript's first entry is always `assistant`
    — prepend a synthetic opening user turn (never persisted) to keep every call valid.
    """
    settings = get_settings()
    transcript = get_transcript(session_id)[-settings.max_context_messages :]
    history = [{"role": m["role"], "content": m["content"]} for m in transcript]
    if not history or history[0]["role"] != "user":
        history = [{"role": "user", "content": "(The candidate has just opened the chat link.)"}] + history
    return history


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def create_session(job_id: int, candidate_id: int, selected_question_ids: list[int] | None = None) -> dict:
    get_job(job_id)  # raises if missing
    candidate = get_candidate(candidate_id)

    screening_result = candidate["screening_result"]
    if screening_result and screening_result.get("mandatory_gate") == "REJECTED":
        reason = screening_result.get("gate_failure_reason", "failed a mandatory JD condition")
        raise ScreeningGateError(
            f"{candidate['name']} was rejected at the mandatory gate ({reason}) and cannot be sent a screening link."
        )

    settings = get_settings()
    token = secrets.token_urlsafe(24)
    now = _now()
    expires_at = now + timedelta(minutes=settings.screening_link_ttl_minutes)
    question_ids_json = json.dumps(selected_question_ids) if selected_question_ids else None

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO screening_sessions
                   (token, candidate_id, job_id, status, phase, selected_question_ids, created_at, expires_at)
               VALUES (?, ?, ?, 'active', 'GREETING', ?, ?, ?)""",
            (token, candidate_id, job_id, question_ids_json, _iso(now), _iso(expires_at)),
        )
        conn.commit()
        session_id = cur.lastrowid

    return {"session_id": session_id, "token": token, "expires_at": _iso(expires_at)}


def _expire_if_needed(session: dict) -> dict:
    if session["status"] == "active" and _now() > datetime.fromisoformat(session["expires_at"]):
        _update_session(session["id"], status="expired")
        session["status"] = "expired"
    return session


def get_session(token: str) -> dict:
    session = _get_session_row(token)
    if not session:
        raise SessionNotFoundError(f"no session for token {token}")
    return _expire_if_needed(session)


# ---------------------------------------------------------------------------
# Turn instruction builders that need the session/job/candidate context
# ---------------------------------------------------------------------------


async def _generate(session: dict, candidate: dict, job: dict, turn_instruction: str, kb_context: str | None = None) -> str:
    system = prompts.build_system_prompt(candidate["profile"], job, turn_instruction, kb_context)
    return await llm_client.call_text(system, _llm_history(session["id"]))


async def _generate_json(session: dict, candidate: dict, job: dict, turn_instruction: str) -> dict:
    system = prompts.build_system_prompt(candidate["profile"], job, turn_instruction)
    return await llm_client.call_json(system, _llm_history(session["id"]))


async def _finalize_session(session: dict, candidate: dict) -> None:
    _update_session(
        session["id"],
        status="completed",
        phase="ENDED",
        completed_at=_iso(_now()),
    )
    try:
        await summarize_session(session["id"], candidate["profile"])
    except Exception:
        # Summary generation failing should never block ending the session —
        # the raw transcript/answers are already persisted regardless.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def start_session(token: str) -> dict:
    session = get_session(token)
    if session["status"] != "active":
        return _terminal_response(session)

    existing = get_transcript(session["id"])
    if existing:
        return {
            "session_status": session["status"],
            "phase": session["phase"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in existing],
        }

    candidate = get_candidate(session["candidate_id"])
    job = get_job(session["job_id"])
    questions = get_session_questions(session)

    # Fixed, deterministic opening — no LLM call, so the "about Seclore" boilerplate (and
    # the first question itself) can never drift or be hallucinated/improvised. We already
    # have the candidate's name on file, so there's no separate "what's your name" round
    # trip. Always opens with a warm icebreaker (never a direct/logistics question like
    # "are you okay relocating?") before moving into the recruiter's selected questions —
    # current_question_index=-1 marks "icebreaker asked, real questions haven't started".
    first_question = prompts.ICEBREAKER_QUESTION if questions else None
    reply = prompts.build_intro_message(candidate["name"], job["title"], first_question)

    if questions:
        _update_session(session["id"], phase="MANDATORY", current_question_index=-1)
        phase = "MANDATORY"
    else:
        _update_session(session["id"], phase="SECLORE_QA", seclore_qa_count=0)
        phase = "SECLORE_QA"
    _save_message(session["id"], "assistant", reply, phase)

    return {"session_status": "active", "phase": phase, "messages": [{"role": "assistant", "content": reply}]}


def _terminal_response(session: dict) -> dict:
    message = prompts.EXPIRED_LINK_MESSAGE if session["status"] == "expired" else prompts.ALREADY_ENDED_MESSAGE
    return {"session_status": session["status"], "phase": session["phase"], "messages": [{"role": "assistant", "content": message}]}


async def handle_message(token: str, user_text: str) -> dict:
    session = get_session(token)
    if session["status"] != "active":
        return _terminal_response(session)

    candidate = get_candidate(session["candidate_id"])
    job = get_job(session["job_id"])
    phase = session["phase"]

    _save_message(session["id"], "user", user_text, phase)

    if phase == "MANDATORY":
        return await _handle_mandatory(session, candidate, job, user_text)
    if phase == "PROFILE_FOLLOWUP":
        return await _handle_profile_followup(session, candidate, job, user_text)
    if phase == "SECLORE_QA":
        return await _handle_seclore_qa(session, candidate, job, user_text)

    # GREETING/ENDED shouldn't normally receive a message here; treat as already-ended.
    return _terminal_response(session)


async def _handle_mandatory(session: dict, candidate: dict, job: dict, user_text: str) -> dict:
    settings = get_settings()
    questions = get_session_questions(session)
    index = session["current_question_index"]

    if index == -1:
        # They just answered the icebreaker, not one of the real screening questions —
        # record it as such (not tied to a job_questions row) and move into question 0.
        _save_answer(session["id"], None, prompts.ICEBREAKER_QUESTION, "icebreaker", user_text)
        instruction = prompts.ask_next_mandatory_question(questions[0]["question_text"], new_section=True)
        reply = await _generate(session, candidate, job, instruction)
        _update_session(session["id"], current_question_index=0)
        _save_message(session["id"], "assistant", reply, "MANDATORY")
        return {"session_status": "active", "phase": "MANDATORY", "messages": [{"role": "assistant", "content": reply}]}

    current_question = questions[index]
    _save_answer(session["id"], current_question["id"], current_question["question_text"], "mandatory", user_text)

    next_index = index + 1
    if next_index < len(questions):
        new_section = questions[next_index].get("source") != current_question.get("source")
        instruction = prompts.ask_next_mandatory_question(questions[next_index]["question_text"], new_section)
        reply = await _generate(session, candidate, job, instruction)
        _update_session(session["id"], current_question_index=next_index)
        _save_message(session["id"], "assistant", reply, "MANDATORY")
        return {"session_status": "active", "phase": "MANDATORY", "messages": [{"role": "assistant", "content": reply}]}

    _update_session(session["id"], phase="PROFILE_FOLLOWUP", profile_followup_count=0)
    session = {**session, "phase": "PROFILE_FOLLOWUP", "profile_followup_count": 0}
    return await _advance_profile_followup(session, candidate, job, settings)


async def _advance_profile_followup(session: dict, candidate: dict, job: dict, settings) -> dict:
    if session["profile_followup_count"] >= settings.max_profile_followups:
        return await _start_seclore_qa(session, candidate, job)

    decision = await _generate_json(session, candidate, job, prompts.PROFILE_FOLLOWUP_DECISION_INSTRUCTION)
    if not decision.get("ask_question") or not decision.get("question"):
        return await _start_seclore_qa(session, candidate, job)

    question = decision["question"]
    instruction = prompts.ask_profile_followup(question)
    reply = await _generate(session, candidate, job, instruction)

    new_count = session["profile_followup_count"] + 1
    _update_session(session["id"], profile_followup_count=new_count, pending_question_text=question)
    _save_message(session["id"], "assistant", reply, "PROFILE_FOLLOWUP")

    return {"session_status": "active", "phase": "PROFILE_FOLLOWUP", "messages": [{"role": "assistant", "content": reply}]}


async def _handle_profile_followup(session: dict, candidate: dict, job: dict, user_text: str) -> dict:
    settings = get_settings()
    _save_answer(session["id"], None, session["pending_question_text"] or "", "profile_followup", user_text)
    return await _advance_profile_followup(session, candidate, job, settings)


async def _start_seclore_qa(session: dict, candidate: dict, job: dict) -> dict:
    _update_session(session["id"], phase="SECLORE_QA", seclore_qa_count=0)
    reply = prompts.build_seclore_qa_intro_message(candidate["name"])
    _save_message(session["id"], "assistant", reply, "SECLORE_QA")
    return {"session_status": "active", "phase": "SECLORE_QA", "messages": [{"role": "assistant", "content": reply}]}


async def _handle_seclore_qa(session: dict, candidate: dict, job: dict, user_text: str) -> dict:
    settings = get_settings()
    classification = await _generate_json(session, candidate, job, prompts.SECLORE_QA_CLASSIFY_INSTRUCTION)

    if not classification.get("has_more_questions"):
        reply = prompts.build_closing_message(candidate["name"])
        _save_message(session["id"], "assistant", reply, "ENDED")
        await _finalize_session(session, candidate)
        return {"session_status": "completed", "phase": "ENDED", "messages": [{"role": "assistant", "content": reply}]}

    query = classification.get("question_for_kb") or user_text
    kb_context = retriever.retrieve(query, settings.rag_top_k)

    new_count = session["seclore_qa_count"] + 1
    is_last_turn = new_count >= settings.max_seclore_qa_turns
    instruction = prompts.answer_seclore_question(is_last_turn)
    reply = await _generate(session, candidate, job, instruction, kb_context=kb_context)

    if is_last_turn:
        reply = f"{reply}\n\n{prompts.build_closing_message(candidate['name'])}"
    _save_message(session["id"], "assistant", reply, "SECLORE_QA")

    if is_last_turn:
        await _finalize_session(session, candidate)
        return {"session_status": "completed", "phase": "ENDED", "messages": [{"role": "assistant", "content": reply}]}

    _update_session(session["id"], seclore_qa_count=new_count)
    return {"session_status": "active", "phase": "SECLORE_QA", "messages": [{"role": "assistant", "content": reply}]}
