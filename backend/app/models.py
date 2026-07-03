"""All Pydantic models for the app live here, shared across pipeline/conversations/api."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    app_env: str
