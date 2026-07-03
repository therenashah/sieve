"""Recruiter login. Single hardcoded account — see app/auth.py."""

from fastapi import APIRouter, HTTPException

from app.auth import create_session, verify_credentials
from app.models import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    if not verify_credentials(body.email, body.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token, expires_at = create_session()
    return LoginResponse(token=token, expires_at=expires_at)
