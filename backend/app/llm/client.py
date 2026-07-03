"""Async-facing LLM entry point used by pipeline/conversation code.

Delegates to the sync Bedrock wrapper (`app.llm.bedrock`) via a thread, so
FastAPI request handlers can `await` it without blocking the event loop.
"""

import asyncio

from app.llm import bedrock


async def call_text(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 1024,
) -> str:
    return await asyncio.to_thread(bedrock.invoke_claude, system, messages, max_tokens=max_tokens)


async def call_json(
    system: str,
    messages: list[dict],
    *,
    max_tokens: int = 512,
) -> dict:
    return await asyncio.to_thread(bedrock.invoke_claude_json, system, messages, max_tokens=max_tokens)
