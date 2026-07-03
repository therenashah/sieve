"""Async-facing LLM entry points used by pipeline/conversation code.

Delegates to the sync Bedrock wrapper (`app.llm.bedrock`) via threads, so
FastAPI request handlers can `await` these without blocking the event loop.
A single `asyncio.Semaphore(4)` caps concurrent provider calls across all
three functions, and every call logs to `audit_log`.

- call_text(system, messages) -> str
    Free-form chat replies. Used by the HR screening conversation engine.
- call_json(system, messages) -> dict
    Loosely-structured JSON turns (e.g. "ask_question: true/false"). Also
    used by the conversation engine.
- call_structured(prompt, response_model, ...) -> T
    Schema-validated Pydantic output, with retry-on-validation-failure and
    backoff on throttling/5xx errors. Used by the resume-screening pipeline
    (rubric generation, scoring). This is what the LLD calls `call_json` —
    renamed here because the conversation engine's `call_json` above already
    has a different, incompatible signature (no response_model, returns a
    plain dict) and was built first.
"""

import asyncio
import json
import time
from typing import TypeVar

from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.db import get_db
from app.llm import bedrock

_MAX_CONCURRENT_CALLS = 4
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CALLS)

_BACKOFF_SCHEDULE_SECONDS = (1, 4)
_RETRYABLE_BEDROCK_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
}

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


async def call_text(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
) -> str:
    model = get_settings().bedrock_model_id
    async with _semaphore:
        started = time.monotonic()
        try:
            text = await asyncio.to_thread(bedrock.invoke_claude, system, messages, max_tokens=max_tokens)
        except ClientError:
            _log_llm_call("call_text", model, int((time.monotonic() - started) * 1000), ok=False)
            raise
        _log_llm_call("call_text", model, int((time.monotonic() - started) * 1000), ok=True)
        return text


async def call_json(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 512,
) -> dict:
    model = get_settings().bedrock_model_id
    async with _semaphore:
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(
                bedrock.invoke_claude_json, system, messages, max_tokens=max_tokens
            )
        except (ClientError, ValueError):
            _log_llm_call("call_json", model, int((time.monotonic() - started) * 1000), ok=False)
            raise
        _log_llm_call("call_json", model, int((time.monotonic() - started) * 1000), ok=True)
        return result


async def call_structured(
    prompt: str,
    response_model: type[T],
    *,
    max_retries: int = 2,
    temperature: float = 0.0,
    purpose: str = "unspecified",
) -> T:
    """Call the LLM and parse+validate its response as `response_model`.

    Retries on invalid JSON/schema mismatches by feeding the error back to the
    model, and on throttling/5xx Bedrock errors via exponential backoff (both
    count against the same `max_retries` budget). Note boto3's own client
    (see bedrock._get_client) already retries transient errors internally up
    to 3 times before raising here — this backoff is a second-layer safety
    net, not the primary retry mechanism. Raises `PipelineLLMError` once
    retries are exhausted.
    """
    model = get_settings().bedrock_model_id
    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_error: Exception | None = None
    backoff_attempts = 0

    async with _semaphore:
        for attempt in range(max_retries + 1):
            started = time.monotonic()
            try:
                text = await asyncio.to_thread(
                    bedrock.invoke_claude,
                    _JSON_ONLY_SUFFIX,
                    messages,
                    max_tokens=4096,
                    temperature=temperature,
                )
            except ClientError as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                _log_llm_call(purpose, model, latency_ms, ok=False)
                last_error = exc
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in _RETRYABLE_BEDROCK_ERROR_CODES:
                    raise PipelineLLMError(str(exc)) from exc
                if attempt < max_retries:
                    delay = _BACKOFF_SCHEDULE_SECONDS[
                        min(backoff_attempts, len(_BACKOFF_SCHEDULE_SECONDS) - 1)
                    ]
                    backoff_attempts += 1
                    await asyncio.sleep(delay)
                continue

            latency_ms = int((time.monotonic() - started) * 1000)
            cleaned = _strip_json_fences(text)

            try:
                parsed = response_model.model_validate_json(cleaned)
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
