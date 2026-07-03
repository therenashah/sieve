"""Candidate-facing screening chat: no login, just a tokenized link."""

from fastapi import APIRouter, HTTPException

from app.conversations import engine
from app.models import ChatMessageRequest, ChatTurnResponse, SessionStatusResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/{token}", response_model=SessionStatusResponse)
async def get_session_status(token: str):
    try:
        session = engine.get_session(token)
    except engine.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid screening link") from exc

    candidate = engine.get_candidate(session["candidate_id"])
    job = engine.get_job(session["job_id"])
    transcript = engine.get_transcript(session["id"])

    return SessionStatusResponse(
        session_status=session["status"],
        phase=session["phase"],
        candidate_name=candidate["name"],
        job_title=job["title"],
        messages=[{"role": m["role"], "content": m["content"]} for m in transcript],
    )


@router.post("/{token}/start", response_model=ChatTurnResponse)
async def start_chat(token: str):
    try:
        result = await engine.start_session(token)
    except engine.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid screening link") from exc
    return ChatTurnResponse(**result)


@router.post("/{token}/message", response_model=ChatTurnResponse)
async def send_message(token: str, body: ChatMessageRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        result = await engine.handle_message(token, body.message.strip())
    except engine.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Invalid screening link") from exc
    return ChatTurnResponse(**result)
