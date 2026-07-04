"""AWS Polly text-to-speech for the AI interviewer's voice.

Kept deliberately small and best-effort: the interview engine calls `synthesize`
to turn an assistant turn into an mp3 (returned as raw bytes), which the candidate
router base64-encodes into the turn response so the browser can play it. If Polly
isn't available (no permission, region issue, throttling), `synthesize` returns
None and the frontend falls back to the browser's built-in SpeechSynthesis — the
interview is never blocked on TTS.

Auth: boto3's default credential chain, same as the Bedrock client.
"""

import asyncio
import re

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

_client = None

# Polly neural voices cap at 3000 characters per request. Interview turns are short
# (< 80 words), but guard anyway so a runaway turn can't throw.
_MAX_TTS_CHARS = 2800


def _get_client():
    global _client
    if _client is None:
        settings = get_settings()
        _client = boto3.client(
            "polly",
            region_name=settings.aws_region,
            config=BotoConfig(retries={"max_attempts": 2, "mode": "standard"}),
        )
    return _client


def _clean_for_speech(text: str) -> str:
    """Strip emoji / markdown so the voice reads naturally (the same assistant text
    is still shown on screen with its formatting)."""
    text = re.sub(r"[*_`#>]", "", text)
    # Drop most non-speech symbols and emoji; keep sentence punctuation.
    text = re.sub(r"[^\w\s.,!?;:'\"()\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_TTS_CHARS]


def _synthesize_sync(text: str) -> bytes | None:
    cleaned = _clean_for_speech(text)
    if not cleaned:
        return None
    settings = get_settings()
    try:
        response = _get_client().synthesize_speech(
            Text=cleaned,
            OutputFormat="mp3",
            VoiceId=settings.polly_voice_id,
            Engine=settings.polly_engine,
        )
        stream = response.get("AudioStream")
        return stream.read() if stream else None
    except (ClientError, BotoCoreError):
        return None


async def synthesize(text: str) -> bytes | None:
    """Return mp3 bytes for `text`, or None if TTS is unavailable (best-effort)."""
    if not text or not text.strip():
        return None
    return await asyncio.to_thread(_synthesize_sync, text)
