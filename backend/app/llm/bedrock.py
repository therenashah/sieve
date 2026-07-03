"""Thin sync wrapper around AWS Bedrock's `invoke_model` for Claude (Messages
API format). Kept synchronous (boto3 has no native async client) — callers on
the async path run these via `asyncio.to_thread`.

Auth: boto3's default credential chain — on the hackathon EC2 instance this
resolves automatically via the attached IAM role (no static keys needed); set
AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN if running elsewhere.
"""

import json

import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings

_client = None


def _get_client():
    global _client
    if _client is None:
        settings = get_settings()
        _client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
        )
    return _client


def invoke_claude(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> str:
    """messages: list of {"role": "user"|"assistant", "content": str}, Anthropic format."""
    settings = get_settings()
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    response = _get_client().invoke_model(
        modelId=settings.bedrock_model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(response["body"].read())
    return "".join(
        block["text"] for block in payload.get("content", []) if block.get("type") == "text"
    )


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def invoke_claude_json(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 512,
    max_retries: int = 2,
    temperature: float | None = None,
) -> dict:
    """Same as invoke_claude, but parses the reply as JSON, retrying on malformed output."""
    working_messages = list(messages)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        text = invoke_claude(system, working_messages, max_tokens=max_tokens, temperature=temperature)
        try:
            return json.loads(_strip_json_fence(text))
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt < max_retries:
                working_messages = working_messages + [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "That was not valid JSON. Reply again with ONLY valid JSON, no prose, no markdown fences.",
                    },
                ]

    raise ValueError(f"Bedrock did not return valid JSON after {max_retries + 1} attempts") from last_error
