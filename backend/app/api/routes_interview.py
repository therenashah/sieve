"""Candidate-facing AI interview round: no login, just a tokenized link.

Flow the candidate sees on one URL (`/interview/{token}`):
  invited   -> pick a slot within the invite window (schedule)
  scheduled -> join the room, run the spoken interview
  completed -> thank-you

Assistant turns carry inline base64 mp3 (Polly). If Polly is unavailable the field
is null and the browser falls back to its own speech synthesis — the interview is
never blocked on TTS.
"""

import base64

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.conversations import interview
from app.db import get_db
from app.llm import voice
from app.models import (
    InterviewMessageRequest,
    InterviewStatusResponse,
    InterviewTurnMessage,
    InterviewTurnResponse,
    ProctorEventRequest,
    ScheduleInterviewRequest,
)
from app.storage import candidates_dir

router = APIRouter(prefix="/api/interview", tags=["interview"])


def _round_name(job_id: int, round_key: str) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM job_rounds WHERE job_id = ? AND round_key = ?", (job_id, round_key)
        ).fetchone()
    return row["name"] if row else "AI Interview"


async def _to_turn_messages(messages: list[dict]) -> list[InterviewTurnMessage]:
    """Attach Polly audio to assistant turns (best-effort)."""
    out: list[InterviewTurnMessage] = []
    for m in messages:
        audio_b64 = None
        if m["role"] == "assistant":
            audio = await voice.synthesize(m["content"])
            if audio:
                audio_b64 = base64.b64encode(audio).decode("ascii")
        out.append(InterviewTurnMessage(role=m["role"], content=m["content"], audio_b64=audio_b64))
    return out


async def _turn_response(result: dict) -> InterviewTurnResponse:
    return InterviewTurnResponse(
        status=result["status"],
        phase=result["phase"],
        messages=await _to_turn_messages(result["messages"]),
        remaining_seconds=result.get("remaining_seconds"),
        should_wrap_up=result.get("should_wrap_up", False),
    )


@router.get("/{token}", response_model=InterviewStatusResponse)
async def get_status(token: str):
    try:
        session = interview.get_session(token)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc

    candidate = interview.engine.get_candidate(session["candidate_id"])
    job = interview.engine.get_job(session["job_id"])
    config = interview._config(session)
    timing = interview._timing(session)

    slots: list[str] = []
    messages: list[InterviewTurnMessage] = []
    if session["status"] in ("invited", "scheduled"):
        slots = interview.offered_slots(session)
    if session["status"] == "in_progress":
        transcript = interview.get_transcript(session["id"])
        # No audio on the status replay — the client plays audio only for fresh turns.
        messages = [InterviewTurnMessage(role=m["role"], content=m["content"]) for m in transcript]

    return InterviewStatusResponse(
        status=session["status"],
        phase=session["phase"],
        candidate_name=candidate["name"],
        job_title=job["title"],
        round_name=_round_name(session["job_id"], session["round_key"]),
        instructions=config.get("instructions", ""),
        duration_minutes=session["duration_minutes"],
        store_recording=bool(config.get("store_recording", False)),
        allow_candidate_questions=bool(config.get("allow_candidate_questions", True)),
        scheduled_at=session.get("scheduled_at"),
        expires_at=session["expires_at"],
        slots=slots,
        messages=messages,
        remaining_seconds=timing["remaining_seconds"] if session["status"] == "in_progress" else None,
    )


@router.post("/{token}/schedule")
async def schedule(token: str, body: ScheduleInterviewRequest):
    try:
        result = interview.schedule_session(token, body.slot)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc
    except interview.InterviewStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/{token}/start", response_model=InterviewTurnResponse)
async def start(token: str):
    try:
        result = await interview.start_interview(token)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc
    return await _turn_response(result)


@router.post("/{token}/message", response_model=InterviewTurnResponse)
async def message(token: str, body: InterviewMessageRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        result = await interview.handle_message(token, body.message.strip())
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc
    return await _turn_response(result)


@router.post("/{token}/end", response_model=InterviewTurnResponse)
async def end(token: str):
    try:
        result = await interview.end_interview(token)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc
    return await _turn_response(result)


@router.post("/{token}/event")
async def proctor_event(token: str, body: ProctorEventRequest):
    try:
        session = interview.get_session(token)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc
    interview.log_event(session["id"], body.type, body.detail)
    return {"ok": True}


@router.post("/{token}/recording")
async def upload_recording(token: str, file: UploadFile = File(...)):
    try:
        session = interview.get_session(token)
    except interview.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid interview link") from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty recording")
    dest_dir = candidates_dir(session["job_id"])
    filename = f"{session['id']}_interview.webm"
    (dest_dir / filename).write_bytes(content)
    interview.set_recording_path(session["id"], filename)
    return {"ok": True, "bytes": len(content)}
