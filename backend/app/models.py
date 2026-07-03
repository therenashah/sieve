"""All Pydantic models for the app live here, shared across pipeline/conversations/api."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    app_env: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


class TriggerScreeningResponse(BaseModel):
    token: str
    chat_url: str
    expires_at: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatTurnResponse(BaseModel):
    session_status: str  # active | completed | expired
    phase: str
    messages: list[ChatMessage]


class ChatMessageRequest(BaseModel):
    message: str


class SessionStatusResponse(BaseModel):
    session_status: str
    phase: str
    candidate_name: str
    job_title: str
    messages: list[ChatMessage]
