"""AI interview round — a spoken, adaptive, timed interview state machine.

Mirrors the HR screening engine's shape (tokenized session, transcript table,
deterministic framing, LLM-driven middle) but for the video/audio interview round:

- Recruiter triggers an interview -> `create_session` mints a token + invite link.
- Candidate opens the link, picks a slot within the invite window (`schedule_session`),
  then joins the tokenized room.
- `start_interview` generates an adaptive question PLAN with the smart model (from
  whatever the round's RoundAIConfig says to share — JD, profile, resume, previous
  rounds, rubric), then opens with a fixed spoken intro + the first question.
- `handle_message` runs one turn: cheap/fast model for "can you repeat", smart model
  for the real decision (probe deeper vs next planned question vs wrap up) — bounded
  by a per-question follow-up cap and a hard timer.
- Past the target duration the interview wraps up; past duration + grace it is force-
  ended. On completion `finalize` scores the transcript with the smart model and
  upserts the shared `round_results` row keyed by this round's key.

Audio (Polly TTS) is added by the router, not here — the engine stays text-only.
"""

import json
import math
import secrets
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.conversations import engine  # reuse get_job / get_candidate / SessionNotFoundError
from app.db import get_db
from app.llm import client as llm_client
from app.llm import prompts

SessionNotFoundError = engine.SessionNotFoundError


class InterviewStateError(Exception):
    """Invalid round (not found / not AI-based) or invalid state transition."""


class InterviewGateError(Exception):
    """Candidate failed the resume-screening mandatory gate — should never reach an interview."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


def _get_round(job_id: int, round_key: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM job_rounds WHERE job_id = ? AND round_key = ?", (job_id, round_key)
        ).fetchone()
    return dict(row) if row else None


def _get_session_row(token: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM interview_sessions WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def _update_session(session_id: int, **fields) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    with get_db() as conn:
        conn.execute(
            f"UPDATE interview_sessions SET {columns} WHERE id = ?", (*fields.values(), session_id)
        )
        conn.commit()


def _save_message(session_id: int, role: str, content: str, kind: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO interview_messages (session_id, role, content, kind) VALUES (?, ?, ?, ?)",
            (session_id, role, content, kind),
        )
        conn.commit()


def get_transcript(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, kind, created_at FROM interview_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def log_event(session_id: int, event_type: str, detail: str = "") -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO interview_events (session_id, type, detail) VALUES (?, ?, ?)",
            (session_id, event_type, detail),
        )
        conn.commit()


def get_events(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT type, detail, created_at FROM interview_events WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_recording_path(session_id: int, path: str) -> None:
    _update_session(session_id, recording_path=path)


def _config(session: dict) -> dict:
    try:
        return json.loads(session["config_json"]) if session["config_json"] else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Context assembly (honours the round's share_* config flags)
# ---------------------------------------------------------------------------


def _previous_round_results(candidate_id: int, exclude_round: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rr.round, rr.score, rr.summary, rr.key_highlights_json, rr.flags_json,
                      COALESCE(jr.name, rr.round) AS name
               FROM round_results rr
               LEFT JOIN job_rounds jr ON jr.round_key = rr.round
                    AND jr.job_id = (SELECT job_id FROM candidates WHERE id = ?)
               WHERE rr.candidate_id = ? AND rr.round != ?
               ORDER BY rr.updated_at ASC""",
            (candidate_id, candidate_id, exclude_round),
        ).fetchall()
    return [dict(r) for r in rows]


def _latest_rubric(job_id: int) -> list[dict] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT criteria_json FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1", (job_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["criteria_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def _build_context_block(config: dict, job: dict, candidate: dict, round_key: str) -> str:
    parts: list[str] = [f"Role being interviewed for: {job['title']}"]

    difficulty = config.get("difficulty", "balanced")
    parts.append(f"Target difficulty: {difficulty}")
    if config.get("focus_areas", "").strip():
        parts.append(f"Recruiter's focus areas for this interview: {config['focus_areas'].strip()}")
    if config.get("instructions", "").strip():
        parts.append(f"Recruiter's instructions to you (the interviewer): {config['instructions'].strip()}")

    if config.get("share_jd", True):
        jd = (job.get("description") or "").strip() or (job.get("jd_text") or "").strip()
        if jd:
            parts.append(f"Job description:\n{jd[:5000]}")

    if config.get("share_profile", True):
        parts.append(f"Candidate profile (from their resume):\n{json.dumps(candidate['profile'], indent=2)}")

    if config.get("share_resume", True) and candidate.get("resume_text"):
        parts.append(f"Candidate resume text (excerpt):\n{candidate['resume_text'][:6000]}")

    if config.get("share_previous_rounds", True):
        prev = _previous_round_results(candidate["id"], round_key)
        if prev:
            lines = []
            for r in prev:
                highlights = ", ".join(json.loads(r["key_highlights_json"]) if r["key_highlights_json"] else [])
                score = f"{r['score']}/100" if r["score"] is not None else "n/a"
                summary = (r["summary"] or "").strip()
                lines.append(f"- {r['name']} (score {score}): {summary} {('Highlights: ' + highlights) if highlights else ''}".strip())
            parts.append("How the candidate did in earlier rounds (for your awareness — do not read these out):\n" + "\n".join(lines))

    if config.get("share_rubric", True):
        rubric = _latest_rubric(job["id"])
        if rubric:
            crit = "\n".join(f"- {c.get('name', '')}: {c.get('description', '')}" for c in rubric)
            parts.append("Role scoring rubric (internal — never read out or reference to the candidate):\n" + crit)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _llm_history(session_id: int) -> list[dict]:
    """Interview transcript as Bedrock messages: candidate->user, interviewer->assistant.
    Merge consecutive same-role turns and ensure the history starts with a user turn."""
    settings = get_settings()
    transcript = get_transcript(session_id)[-settings.max_context_messages :]
    history: list[dict] = []
    for m in transcript:
        role = "assistant" if m["role"] == "assistant" else "user"
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n" + m["content"]
        else:
            history.append({"role": role, "content": m["content"]})
    if not history or history[0]["role"] != "user":
        history = [{"role": "user", "content": "(The candidate has just joined the interview.)"}] + history
    return history


async def _smart_json(session: dict, context_block: str, instruction: str) -> dict:
    system = prompts.build_interview_system_prompt(context_block, instruction)
    return await llm_client.call_json(
        system, _llm_history(session["id"]), max_tokens=600, model=get_settings().smart_model_id
    )


async def _smart_text(session: dict, context_block: str, instruction: str) -> str:
    system = prompts.build_interview_system_prompt(context_block, instruction)
    return await llm_client.call_text(
        system, _llm_history(session["id"]), max_tokens=400, model=get_settings().smart_model_id
    )


async def _fast_text(session: dict, context_block: str, instruction: str) -> str:
    system = prompts.build_interview_system_prompt(context_block, instruction)
    return await llm_client.call_text(
        system, _llm_history(session["id"]), max_tokens=300, model=get_settings().fast_model_id
    )


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def _wrap_threshold_minutes(duration: int) -> int:
    return max(2, math.ceil(duration * 0.12))


def _timing(session: dict) -> dict:
    """Returns remaining_seconds (until hard stop), remaining_minutes, must_wrap, should_wrap."""
    settings = get_settings()
    duration = session["duration_minutes"]
    if not session.get("started_at"):
        return {"remaining_seconds": duration * 60, "remaining_minutes": duration, "must_wrap": False, "should_wrap": False}
    started = _parse_dt(session["started_at"])
    elapsed = (_now() - started).total_seconds()
    hard_limit = (duration + settings.interview_hard_stop_grace_minutes) * 60
    remaining = max(0, int(hard_limit - elapsed))
    remaining_target_min = max(0, math.ceil((duration * 60 - elapsed) / 60))
    threshold = _wrap_threshold_minutes(duration)
    must_wrap = elapsed >= hard_limit  # past grace -> force
    should_wrap = remaining_target_min <= threshold
    return {
        "remaining_seconds": remaining,
        "remaining_minutes": remaining_target_min,
        "must_wrap": must_wrap or remaining_target_min <= 0,
        "should_wrap": should_wrap,
    }


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def create_session(job_id: int, candidate_id: int, round_key: str) -> dict:
    from app.models import RoundAIConfig

    engine.get_job(job_id)
    candidate = engine.get_candidate(candidate_id)

    round_row = _get_round(job_id, round_key)
    if not round_row:
        raise InterviewStateError(f"Round '{round_key}' not found for this job.")
    if not round_row["is_ai_based"]:
        raise InterviewStateError(f"Round '{round_row['name']}' is not configured as an AI interview.")

    screening_result = candidate["screening_result"]
    if screening_result and screening_result.get("mandatory_gate") == "REJECTED":
        reason = screening_result.get("gate_failure_reason", "failed a mandatory JD condition")
        raise InterviewGateError(
            f"{candidate['name']} was rejected at the mandatory gate ({reason}) and cannot be sent an interview."
        )

    # Snapshot config, filling defaults for any field the stored config omits.
    raw_config = {}
    if round_row["ai_config_json"]:
        try:
            raw_config = json.loads(round_row["ai_config_json"])
        except (json.JSONDecodeError, TypeError):
            raw_config = {}
    config = RoundAIConfig(**raw_config).model_dump()
    duration = config["duration_minutes"]

    settings = get_settings()
    token = secrets.token_urlsafe(24)
    now = _now()
    expires_at = now + timedelta(days=settings.interview_link_ttl_days)

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO interview_sessions
                   (token, candidate_id, job_id, round_key, status, phase, config_json, duration_minutes, created_at, expires_at)
               VALUES (?, ?, ?, ?, 'invited', 'INTRO', ?, ?, ?, ?)""",
            (token, candidate_id, job_id, round_key, json.dumps(config), duration, _iso(now), _iso(expires_at)),
        )
        conn.commit()
        session_id = cur.lastrowid

    return {"session_id": session_id, "token": token, "expires_at": _iso(expires_at)}


def _expire_if_needed(session: dict) -> dict:
    active_pre_join = session["status"] in ("invited", "scheduled")
    if active_pre_join and _now() > _parse_dt(session["expires_at"]):
        _update_session(session["id"], status="expired")
        session["status"] = "expired"
    return session


def get_session(token: str) -> dict:
    session = _get_session_row(token)
    if not session:
        raise SessionNotFoundError(f"no interview for token {token}")
    return _expire_if_needed(session)


def offered_slots(session: dict) -> list[str]:
    """Hourly-ish slots within the invite window, from the configured local hours."""
    settings = get_settings()
    try:
        hours = [int(h) for h in settings.interview_scheduling_slot_hours.split(",") if h.strip()]
    except ValueError:
        hours = [9, 11, 13, 15, 17]
    now = _now()
    window_end = _parse_dt(session["expires_at"])
    earliest = now + timedelta(hours=1)  # give at least an hour's lead time
    slots: list[str] = []
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(settings.interview_link_ttl_days + 1):
        for hour in hours:
            slot = day.replace(hour=hour)
            if earliest <= slot <= window_end:
                slots.append(_iso(slot))
        day += timedelta(days=1)
    return slots[:40]


def schedule_session(token: str, slot: str) -> dict:
    session = get_session(token)
    if session["status"] not in ("invited", "scheduled"):
        raise InterviewStateError("This interview can no longer be scheduled.")
    try:
        chosen = _parse_dt(slot)
    except ValueError as exc:
        raise InterviewStateError("Invalid time slot.") from exc
    if chosen > _parse_dt(session["expires_at"]) or chosen < _now() - timedelta(minutes=5):
        raise InterviewStateError("That slot is outside the scheduling window.")
    _update_session(session["id"], scheduled_at=_iso(chosen), status="scheduled")
    return {"scheduled_at": _iso(chosen)}


def _turn(session: dict, messages: list[dict]) -> dict:
    timing = _timing(session)
    return {
        "status": session["status"],
        "phase": session["phase"],
        "messages": messages,
        "remaining_seconds": timing["remaining_seconds"],
        "should_wrap_up": timing["should_wrap"],
    }


def _plan_questions(session: dict) -> list[dict]:
    try:
        plan = json.loads(session["plan_json"]) if session["plan_json"] else {}
    except (json.JSONDecodeError, TypeError):
        plan = {}
    return plan.get("questions", []) if isinstance(plan, dict) else []


async def _generate_plan(context_block: str, config: dict, duration: int) -> dict:
    num_questions = max(3, min(8, round(duration / 6)))
    prompt = prompts.build_interview_plan_prompt(
        context_block, num_questions, config.get("difficulty", "balanced"), config.get("focus_areas", "")
    )
    try:
        plan = await llm_client.call_json(
            "Respond with ONLY valid JSON. No prose, no markdown fences.",
            [{"role": "user", "content": prompt}],
            max_tokens=1500,
            model=get_settings().smart_model_id,
        )
        questions = plan.get("questions") if isinstance(plan, dict) else None
        if questions:
            return plan
    except Exception:
        pass
    # Reliable fallback so an interview can always start even if planning fails.
    return {
        "competencies": ["Experience", "Problem solving", "Communication", "Role fit"],
        "questions": [
            {"topic": "Background", "question": "To start, could you walk me through your current role and what you're responsible for day to day?", "intent": "Baseline experience", "competency": "Experience"},
            {"topic": "Project", "question": "Tell me about a project you're proud of — what was the problem, and what was your specific contribution?", "intent": "Depth and ownership", "competency": "Problem solving"},
            {"topic": "Challenge", "question": "Describe a difficult technical or professional challenge you faced recently and how you worked through it.", "intent": "Problem solving under pressure", "competency": "Problem solving"},
            {"topic": "Collaboration", "question": "Can you give an example of a time you had a disagreement with a colleague or stakeholder, and how you handled it?", "intent": "Communication and collaboration", "competency": "Communication"},
            {"topic": "Motivation", "question": "What are you looking for in your next role, and why does this opportunity interest you?", "intent": "Role fit and motivation", "competency": "Role fit"},
        ],
    }


async def start_interview(token: str) -> dict:
    session = get_session(token)

    if session["status"] in ("completed",):
        return _terminal_turn(session, prompts.INTERVIEW_ENDED_MESSAGE)
    if session["status"] == "expired":
        return _terminal_turn(session, prompts.INTERVIEW_EXPIRED_MESSAGE)

    # Resume: interview already started — replay the transcript so a refresh doesn't restart it.
    if session["status"] == "in_progress":
        transcript = get_transcript(session["id"])
        msgs = [{"role": m["role"], "content": m["content"]} for m in transcript]
        return _turn(session, msgs)

    candidate = engine.get_candidate(session["candidate_id"])
    job = engine.get_job(session["job_id"])
    config = _config(session)
    context_block = _build_context_block(config, job, candidate, session["round_key"])

    plan = await _generate_plan(context_block, config, session["duration_minutes"])
    questions = plan.get("questions", [])
    first_question = questions[0]["question"] if questions else "To start, tell me a bit about your current role."

    intro = prompts.build_interview_intro_message(
        candidate["name"], job["title"], session["duration_minutes"], first_question
    )

    now = _now()
    _update_session(
        session["id"],
        status="in_progress",
        phase="INTERVIEW",
        plan_json=json.dumps(plan),
        current_index=0,
        followups_used=0,
        started_at=_iso(now),
    )
    _save_message(session["id"], "assistant", intro, "intro")

    session = _get_session_row(token)  # refresh for timing
    return _turn(session, [{"role": "assistant", "content": intro}])


def _terminal_turn(session: dict, message: str) -> dict:
    return {
        "status": session["status"],
        "phase": session["phase"],
        "messages": [{"role": "assistant", "content": message}],
        "remaining_seconds": 0,
        "should_wrap_up": False,
    }


_REPEAT_HINTS = (
    "repeat", "say that again", "didn't catch", "did not catch", "come again", "pardon",
    "what was the question", "can you repeat", "could you repeat", "one more time", "didn't hear",
    "did not hear", "rephrase", "not sure i understood", "what do you mean",
)


def _looks_like_repeat(text: str) -> bool:
    t = text.strip().lower()
    if len(t) > 90:
        return False
    return any(hint in t for hint in _REPEAT_HINTS)


async def handle_message(token: str, user_text: str) -> dict:
    session = get_session(token)
    if session["status"] == "expired":
        return _terminal_turn(session, prompts.INTERVIEW_EXPIRED_MESSAGE)
    if session["status"] != "in_progress":
        return _terminal_turn(session, prompts.INTERVIEW_ENDED_MESSAGE)

    candidate = engine.get_candidate(session["candidate_id"])
    job = engine.get_job(session["job_id"])
    config = _config(session)
    context_block = _build_context_block(config, job, candidate, session["round_key"])

    _save_message(session["id"], "candidate", user_text, "answer")
    session = _get_session_row(token)  # refresh
    timing = _timing(session)

    # Past the hard grace limit — end no matter what was said.
    if timing["must_wrap"] and session["phase"] != "WRAPUP":
        closing = prompts.build_interview_closing_message(candidate["name"])
        _save_message(session["id"], "assistant", closing, "closing")
        await _finalize(session, context_block)
        session = _get_session_row(token)
        return _terminal_turn(session, closing)

    if session["phase"] == "WRAPUP":
        return await _handle_wrapup(session, candidate, context_block, user_text)
    return await _handle_interview(session, candidate, config, context_block, timing)


async def _handle_interview(session: dict, candidate: dict, config: dict, context_block: str, timing: dict) -> dict:
    questions = _plan_questions(session)
    index = session["current_index"]

    # "Can you repeat that?" — re-ask the current question, don't advance.
    transcript = get_transcript(session["id"])
    last_msg = transcript[-1]["content"] if transcript else ""
    if _looks_like_repeat(last_msg) and index < len(questions):
        instruction = prompts.repeat_or_clarify_instruction(questions[index]["question"])
        reply = _clean(await _fast_text(session, context_block, instruction))
        _save_message(session["id"], "assistant", reply, "repeat")
        return _turn(_get_session_row_by_id(session["id"]), [{"role": "assistant", "content": reply}])

    current_question = questions[index]["question"] if index < len(questions) else "your last point"
    next_index = index + 1
    next_question = questions[next_index]["question"] if next_index < len(questions) else None

    settings = get_settings()
    decision = await _smart_json(
        session,
        context_block,
        prompts.build_interview_turn_instruction(
            current_question,
            next_question,
            session["followups_used"],
            settings.interview_max_followups_per_question,
            timing["remaining_minutes"],
            timing["must_wrap"] or timing["should_wrap"],
        ),
    )
    action = (decision.get("action") or "next").strip().lower()
    message = _clean(decision.get("message") or "")

    wrapping = action == "wrap" or (action == "next" and next_question is None) or timing["must_wrap"]

    if wrapping:
        return await _begin_wrap(session, candidate, config, context_block)

    if action == "followup" and session["followups_used"] < settings.interview_max_followups_per_question:
        if not message:
            message = "Could you give me a specific example of that?"
        _save_message(session["id"], "assistant", message, "followup")
        _update_session(session["id"], followups_used=session["followups_used"] + 1)
        return _turn(_get_session_row_by_id(session["id"]), [{"role": "assistant", "content": message}])

    # action == "next" (or fell through) -> advance to the next planned question
    if not message:
        message = next_question or "Let's move on. Tell me more about your experience."
    _save_message(session["id"], "assistant", message, "question")
    _update_session(session["id"], current_index=next_index, followups_used=0)
    return _turn(_get_session_row_by_id(session["id"]), [{"role": "assistant", "content": message}])


async def _begin_wrap(session: dict, candidate: dict, config: dict, context_block: str) -> dict:
    if config.get("allow_candidate_questions", True):
        message = prompts.build_candidate_qa_intro_message(candidate["name"])
        _update_session(session["id"], phase="WRAPUP", followups_used=0)  # reuse followups_used as QA counter
        _save_message(session["id"], "assistant", message, "wrapup")
        return _turn(_get_session_row_by_id(session["id"]), [{"role": "assistant", "content": message}])
    closing = prompts.build_interview_closing_message(candidate["name"])
    _save_message(session["id"], "assistant", closing, "closing")
    await _finalize(session, context_block)
    return _terminal_turn(_get_session_row_by_id(session["id"]), closing)


_QA_CLASSIFY_INSTRUCTION = (
    "The candidate just responded to your offer to answer their questions. Decide whether they asked a real "
    "question they want answered, or indicated they have none (e.g. \"no\", \"I'm good\", \"that's all\"). "
    "Respond with ONLY this JSON: {\"has_question\": true or false}"
)

_MAX_CANDIDATE_QUESTIONS = 2


async def _handle_wrapup(session: dict, candidate: dict, context_block: str, user_text: str) -> dict:
    settings = get_settings()
    classification = await llm_client.call_json(
        prompts.build_interview_system_prompt(context_block, _QA_CLASSIFY_INSTRUCTION),
        _llm_history(session["id"]),
        max_tokens=80,
        model=settings.fast_model_id,
    )
    qa_count = session["followups_used"]
    has_question = bool(classification.get("has_question"))

    if not has_question:
        closing = prompts.build_interview_closing_message(candidate["name"])
        _save_message(session["id"], "assistant", closing, "closing")
        await _finalize(session, context_block)
        return _terminal_turn(_get_session_row_by_id(session["id"]), closing)

    is_last = qa_count + 1 >= _MAX_CANDIDATE_QUESTIONS
    answer = _clean(await _fast_text(session, context_block, prompts.answer_candidate_question_instruction(is_last)))
    if is_last:
        closing = prompts.build_interview_closing_message(candidate["name"])
        reply = f"{answer}\n\n{closing}"
        _save_message(session["id"], "assistant", reply, "closing")
        await _finalize(session, context_block)
        return _terminal_turn(_get_session_row_by_id(session["id"]), reply)

    _save_message(session["id"], "assistant", answer, "wrapup")
    _update_session(session["id"], followups_used=qa_count + 1)
    return _turn(_get_session_row_by_id(session["id"]), [{"role": "assistant", "content": answer}])


async def end_interview(token: str, reason: str = "candidate_ended") -> dict:
    session = get_session(token)
    if session["status"] != "in_progress":
        if session["status"] == "expired":
            return _terminal_turn(session, prompts.INTERVIEW_EXPIRED_MESSAGE)
        return _terminal_turn(session, prompts.INTERVIEW_ENDED_MESSAGE)
    candidate = engine.get_candidate(session["candidate_id"])
    job = engine.get_job(session["job_id"])
    context_block = _build_context_block(_config(session), job, candidate, session["round_key"])
    log_event(session["id"], "interview_ended", reason)
    closing = prompts.build_interview_closing_message(candidate["name"])
    _save_message(session["id"], "assistant", closing, "closing")
    await _finalize(session, context_block)
    return _terminal_turn(_get_session_row_by_id(session["id"]), closing)


# ---------------------------------------------------------------------------
# Finalization + scoring
# ---------------------------------------------------------------------------


async def _finalize(session: dict, context_block: str) -> None:
    _update_session(session["id"], status="completed", phase="ENDED", ended_at=_iso(_now()), completed_at=_iso(_now()))
    config = _config(session)
    if not config.get("generate_scorecard", True):
        return
    try:
        await _score(session["id"], session["candidate_id"], session["round_key"], context_block)
    except Exception:
        # Scoring failure must never block completion — the transcript is already saved.
        pass


async def _score(session_id: int, candidate_id: int, round_key: str, context_block: str) -> dict:
    row = _get_session_row_by_id(session_id)
    plan_json = row["plan_json"] or "{}"
    transcript = get_transcript(session_id)
    transcript_text = "\n".join(
        f"{'INTERVIEWER' if m['role'] == 'assistant' else 'CANDIDATE'}: {m['content']}" for m in transcript
    )
    user_prompt = prompts.build_interview_scoring_user_prompt(context_block, plan_json, transcript_text)
    result = await llm_client.call_json(
        prompts.INTERVIEW_SCORING_SYSTEM_PROMPT,
        [{"role": "user", "content": user_prompt}],
        max_tokens=1500,
        model=get_settings().smart_model_id,
    )

    score = result.get("score")
    if isinstance(score, (int, float)):
        score = max(0, min(100, int(score)))
    else:
        score = None
    summary = result.get("summary", "")
    key_highlights = result.get("key_highlights", []) or []
    flags = result.get("flags", []) or []

    with get_db() as conn:
        conn.execute(
            "UPDATE interview_sessions SET summary = ?, score = ?, scorecard_json = ? WHERE id = ?",
            (summary, score, json.dumps(result), session_id),
        )
        # Upsert the shared round_results row keyed by this round. session_id stays NULL —
        # that FK points at screening_sessions; the interview transcript lives in its own tables.
        conn.execute(
            """INSERT INTO round_results (candidate_id, round, score, summary, key_highlights_json, flags_json, session_id)
               VALUES (?, ?, ?, ?, ?, ?, NULL)
               ON CONFLICT(candidate_id, round) DO UPDATE SET
                   score = excluded.score, summary = excluded.summary,
                   key_highlights_json = excluded.key_highlights_json, flags_json = excluded.flags_json,
                   updated_at = datetime('now')""",
            (candidate_id, round_key, score, summary, json.dumps(key_highlights), json.dumps(flags)),
        )
        conn.commit()
    return result


# ---------------------------------------------------------------------------
# small internal helpers
# ---------------------------------------------------------------------------


def _get_session_row_by_id(session_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row)


def _clean(text: str) -> str:
    """Interviewer turns are spoken — strip stray markdown the model may add."""
    return (text or "").replace("**", "").replace("###", "").replace("*", "").strip()
