"""Candidate-facing chat sessions: /chat/{token}/*."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/{token}")
async def get_session(token: str):
    return {"token": token, "status": "not_implemented"}
