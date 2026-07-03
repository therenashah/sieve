"""Transcript + captured answers -> recruiter-facing summary (LLM pass)."""

import json

from app.db import get_db
from app.llm import client as llm_client
from app.llm import prompts


async def summarize_session(session_id: int) -> dict:
    with get_db() as conn:
        messages = conn.execute(
            "SELECT role, content FROM screening_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        answers = conn.execute(
            "SELECT question_text, question_type, answer_text FROM screening_answers WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()

    transcript_text = "\n".join(f"{row['role'].upper()}: {row['content']}" for row in messages)
    qa_text = "\n".join(
        f"[{row['question_type']}] Q: {row['question_text']}\nA: {row['answer_text']}" for row in answers
    )

    user_prompt = (
        f"## Full transcript\n{transcript_text}\n\n## Captured question/answer pairs\n{qa_text}"
    )
    result = await llm_client.call_json(
        prompts.SUMMARY_SYSTEM_PROMPT,
        [{"role": "user", "content": user_prompt}],
        max_tokens=768,
    )

    with get_db() as conn:
        conn.execute(
            "UPDATE screening_sessions SET summary = ?, key_highlights = ? WHERE id = ?",
            (
                result.get("summary", ""),
                json.dumps({"key_highlights": result.get("key_highlights", []), "concerns": result.get("concerns", [])}),
                session_id,
            ),
        )
        conn.commit()

    return result
