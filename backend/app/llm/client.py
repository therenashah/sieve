"""Shared LLM call wrapper: JSON-structured output, retries, concurrency limiting.

Every pipeline/conversation module that needs an LLM call should go through
`call_json` so retry/validation/rate-limiting behavior stays in one place.
"""

import asyncio
import json
from typing import Any

import anthropic

from app.config import get_settings

_MAX_CONCURRENT_CALLS = 4
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CALLS)


class LLMError(Exception):
    """Raised when the LLM fails to produce valid JSON after all retries."""


async def call_json(
    system_prompt: str,
    user_prompt: str,
    *,
    max_retries: int = 2,
    model: str = "claude-sonnet-5",
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Call the LLM and parse the response as JSON, retrying on invalid output."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    last_error: Exception | None = None
    async with _semaphore:
        for attempt in range(max_retries + 1):
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return json.loads(text)
            except (json.JSONDecodeError, anthropic.APIError) as exc:
                last_error = exc
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)

    raise LLMError(f"LLM call failed after {max_retries + 1} attempts") from last_error
