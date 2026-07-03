"""Recruiter auth: single hardcoded account, opaque bearer tokens in SQLite.

No user table/JWT — this is a single-tenant recruiter tool. Good enough to
gate the recruiter UI behind a login without adding auth infrastructure the
product doesn't need yet.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

from app.config import get_settings
from app.db import get_db


def verify_credentials(email: str, password: str) -> bool:
    settings = get_settings()
    return (
        email.strip().lower() == settings.recruiter_email.strip().lower()
        and password == settings.recruiter_password
    )


def create_session() -> tuple[str, str]:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=settings.recruiter_session_ttl_hours)).isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO recruiter_sessions (token, expires_at) VALUES (?, ?)", (token, expires_at))
        conn.commit()
    return token, expires_at


async def require_auth(authorization: str = Header(default="")) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()

    with get_db() as conn:
        row = conn.execute(
            "SELECT expires_at FROM recruiter_sessions WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
