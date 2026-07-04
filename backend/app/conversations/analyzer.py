"""Transcript + captured answers -> recruiter-facing summary (LLM pass).

Also cross-checks the chat against the candidate's resume-derived profile for
inconsistencies (red/green flags) and proposes an updated fitment score, then
upserts both onto `round_results` for round='hr_screening' — this is what the
candidate detail page reads for the HR Screening round card.
"""

import json

from app.db import get_db
from app.llm import client as llm_client
from app.llm import prompts


async def summarize_session(session_id: int, candidate_profile: dict) -> dict:
    with get_db() as conn:
        messages = conn.execute(
            "SELECT role, content FROM screening_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        answers = conn.execute(
            "SELECT question_text, question_type, answer_text FROM screening_answers WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        session_row = conn.execute(
            "SELECT candidate_id FROM screening_sessions WHERE id = ?", (session_id,)
        ).fetchone()

    transcript_text = "\n".join(f"{row['role'].upper()}: {row['content']}" for row in messages)
    qa_text = "\n".join(
        f"[{row['question_type']}] Q: {row['question_text']}\nA: {row['answer_text']}" for row in answers
    )

    user_prompt = prompts.build_summary_user_prompt(candidate_profile, transcript_text, qa_text)
    result = await llm_client.call_json(
        prompts.SUMMARY_SYSTEM_PROMPT,
        [{"role": "user", "content": user_prompt}],
        max_tokens=1024,
    )

    key_highlights = result.get("key_highlights", [])
    flags = result.get("flags", [])
    summary = result.get("summary", "")

    # Every round writes round_results.score on the same 0-100 scale (resume_screening's
    # weighted rubric average, this fitment score, and interview scorecards -- see
    # interview.py's identical clamp) so the leaderboard's cross-round "overall" average
    # is always comparing like-for-like. Clamp defensively rather than trusting the LLM
    # to stay in range even though the prompt already asks for 0-100.
    updated_score = result.get("updated_fitment_score")
    if isinstance(updated_score, (int, float)):
        updated_score = max(0, min(100, int(updated_score)))
    else:
        updated_score = None

    with get_db() as conn:
        conn.execute(
            "UPDATE screening_sessions SET summary = ?, key_highlights = ? WHERE id = ?",
            (summary, json.dumps({"key_highlights": key_highlights}), session_id),
        )
        if session_row:
            conn.execute(
                """INSERT INTO round_results (candidate_id, round, score, summary, key_highlights_json, flags_json, session_id)
                   VALUES (?, 'hr_screening', ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_id, round) DO UPDATE SET
                       score = excluded.score, summary = excluded.summary,
                       key_highlights_json = excluded.key_highlights_json, flags_json = excluded.flags_json,
                       session_id = excluded.session_id, updated_at = datetime('now')""",
                (
                    session_row["candidate_id"],
                    updated_score,
                    summary,
                    json.dumps(key_highlights),
                    json.dumps(flags),
                    session_id,
                ),
            )
        conn.commit()

    return result
