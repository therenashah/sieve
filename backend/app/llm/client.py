"""Shared LLM call wrapper: JSON-structured output, retries, concurrency limiting.

Every pipeline/conversation module that needs an LLM call goes through
`call_json` so retry/validation/rate-limiting behavior stays in one place.
No module calls the Anthropic SDK directly.
"""

import json
import time
from asyncio import Semaphore, sleep
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.db import get_db

_MAX_CONCURRENT_CALLS = 4
_semaphore = Semaphore(_MAX_CONCURRENT_CALLS)

_MAX_TOKENS = 4096
_BACKOFF_SCHEDULE_SECONDS = (1, 4)

_JSON_ONLY_SUFFIX = (
    "Respond with ONLY valid JSON matching the required schema. "
    "No prose. No markdown fences."
)

T = TypeVar("T", bound=BaseModel)


class PipelineLLMError(Exception):
    """Raised when the LLM fails to produce a valid response after all retries."""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    text = text[3:]
    if text.lower().startswith("json"):
        text = text[4:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _log_llm_call(purpose: str, model: str, latency_ms: int, ok: bool) -> None:
    payload = {"purpose": purpose, "model": model, "latency_ms": latency_ms, "ok": ok}
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_log (entity, action, payload_json) VALUES (?, ?, ?)",
            ("llm", "call", json.dumps(payload)),
        )
        conn.commit()


async def call_json(
    prompt: str,
    response_model: type[T],
    *,
    max_retries: int = 2,
    temperature: float = 0.0,
    purpose: str = "unspecified",
) -> T:
    """Call the LLM and parse+validate its response as `response_model`.

    Retries on invalid JSON/schema mismatches by feeding the error back to the
    model, and on 429/5xx responses via exponential backoff (both count
    against the same `max_retries` budget). Raises `PipelineLLMError` once
    retries are exhausted. `purpose` is a free-text label for the audit_log
    row (e.g. "generate_rubric") — not part of the LLD's literal call_json
    signature, added because section 3 requires it in the audit payload.
    """
    settings = get_settings()
    # No access key/secret passed: boto3 resolves credentials from its default chain,
    # which on the deployment EC2 instance means the instance's IAM role automatically.
    client = anthropic.AsyncAnthropicBedrock(aws_region=settings.aws_region)
    model = settings.llm_model

    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    last_error: Exception | None = None
    backoff_attempts = 0

    async with _semaphore:
        for attempt in range(max_retries + 1):
            started = time.monotonic()
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=_MAX_TOKENS,
                    temperature=temperature,
                    system=_JSON_ONLY_SUFFIX,
                    messages=messages,
                )
            except anthropic.APIStatusError as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                _log_llm_call(purpose, model, latency_ms, ok=False)
                last_error = exc
                if exc.status_code != 429 and exc.status_code < 500:
                    raise PipelineLLMError(str(exc)) from exc
                if attempt < max_retries:
                    delay = _BACKOFF_SCHEDULE_SECONDS[
                        min(backoff_attempts, len(_BACKOFF_SCHEDULE_SECONDS) - 1)
                    ]
                    backoff_attempts += 1
                    await sleep(delay)
                continue

            latency_ms = int((time.monotonic() - started) * 1000)
            text = _strip_json_fences(
                "".join(block.text for block in response.content if block.type == "text")
            )

            try:
                parsed = response_model.model_validate_json(text)
            except ValidationError as exc:
                _log_llm_call(purpose, model, latency_ms, ok=False)
                last_error = exc
                if attempt < max_retries:
                    messages.append({"role": "assistant", "content": text})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Previous output failed validation: {exc}. Return corrected JSON only.",
                        }
                    )
                continue

            _log_llm_call(purpose, model, latency_ms, ok=True)
            return parsed

    raise PipelineLLMError(
        f"LLM call failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error
