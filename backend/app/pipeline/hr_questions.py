"""JD-derived HR screening questions — generated alongside the rubric, stored
in `job_questions` (source='ai') next to the generic defaults (source='default')
so the recruiter picks from one combined pool when triggering a screening chat.
"""

from pydantic import BaseModel

from app.db import get_db
from app.llm.client import call_structured
from app.llm.prompts import HR_QUESTIONS_PROMPT


class _HRQuestionsDraft(BaseModel):
    questions: list[str]


async def generate_hr_questions(jd_text: str) -> list[str]:
    draft = await call_structured(
        HR_QUESTIONS_PROMPT.format(jd_text=jd_text),
        _HRQuestionsDraft,
        purpose="generate_hr_questions",
    )
    return [q.strip() for q in draft.questions if q.strip()]


def add_questions(job_id: int, questions: list[str], source: str) -> None:
    if not questions:
        return
    with get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM job_questions WHERE job_id = ?", (job_id,)
        ).fetchone()["m"]
        for offset, question in enumerate(questions, start=1):
            conn.execute(
                """INSERT INTO job_questions (job_id, question_text, order_index, is_mandatory, source)
                   VALUES (?, ?, ?, 1, ?)""",
                (job_id, question, max_order + offset, source),
            )
        conn.commit()


async def generate_and_apply_hr_questions(job_id: int, jd_text: str) -> None:
    """Background-task entry point, mirrors `pipeline.rubric.generate_and_apply_rubric`."""
    try:
        questions = await generate_hr_questions(jd_text)
        add_questions(job_id, questions, source="ai")
    except Exception as exc:  # noqa: BLE001 - background task, nothing left to propagate to
        print(f"[generate_and_apply_hr_questions] job_id={job_id} failed: {exc}")
