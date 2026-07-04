"""Raw resume text -> structured candidate profile (LLM pass)."""

from app.llm.client import call_structured
from app.llm.prompts import PROFILE_PROMPT
from app.models import Profile


async def extract_profile(resume_text: str) -> Profile:
    return await call_structured(
        PROFILE_PROMPT.format(resume_text=resume_text),
        Profile,
        purpose="extract_profile",
    )
