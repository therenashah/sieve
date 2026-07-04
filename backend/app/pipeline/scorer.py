"""Per-criterion scoring against a rubric, plus selective re-scoring."""

import asyncio
import json

from app import storage
from app.db import get_db
from app.llm.client import call_structured
from app.llm.prompts import SCORING_PROMPT
from app.models import Criterion, Rubric, ScoreSheet
from app.pipeline import parser
from app.pipeline.profile import extract_profile


def _build_resume_screening_result(rubric: Rubric, score_rows: list) -> dict:
    """Turn a candidate's full criterion_scores set under `rubric` into the same shape
    the HR-screening analyzer writes to round_results, so the leaderboard/candidate page
    can render both rounds identically. `score` is a 0-100 percentage — same weighted
    formula (and same rounding) as ranker.rank()'s `overall`, just *100 instead of /10,
    so this always matches what the resume-screening page shows for the same candidate.
    """
    name_by_id = {c.id: c.name for c in rubric.criteria}
    weights = {c.id: c.weight for c in rubric.criteria}
    weighted_avg = sum(row["score"] * weights.get(row["criterion_id"], 0.0) for row in score_rows)
    score_pct = round(weighted_avg * 10)

    ordered = sorted(score_rows, key=lambda r: r["score"], reverse=True)
    key_highlights = [
        f"{name_by_id.get(row['criterion_id'], row['criterion_id'])}: {row['score']}/10"
        + (f" — {row['note']}" if row["note"] else "")
        for row in ordered[:5]
    ]

    flags = []
    for row in score_rows:
        crit_name = name_by_id.get(row["criterion_id"], row["criterion_id"])
        if row["score"] <= 3:
            flags.append({"type": "red", "detail": f"Weak on {crit_name} ({row['score']}/10): {row['evidence']}"})
        elif row["score"] >= 8:
            flags.append({"type": "green", "detail": f"Strong on {crit_name} ({row['score']}/10): {row['evidence']}"})

    summary = f"Scored {score_pct}% against the current rubric across {len(score_rows)} criteria."
    return {"score": score_pct, "summary": summary, "key_highlights": key_highlights, "flags": flags}


def _upsert_resume_screening_round_result(conn, candidate_id: int, rubric_id: int, rubric: Rubric) -> None:
    score_rows = conn.execute(
        "SELECT criterion_id, score, evidence, note FROM criterion_scores WHERE candidate_id = ? AND rubric_id = ?",
        (candidate_id, rubric_id),
    ).fetchall()
    if not score_rows:
        return

    result = _build_resume_screening_result(rubric, score_rows)
    conn.execute(
        """INSERT INTO round_results (candidate_id, round, score, summary, key_highlights_json, flags_json)
           VALUES (?, 'resume_screening', ?, ?, ?, ?)
           ON CONFLICT(candidate_id, round) DO UPDATE SET
               score = excluded.score, summary = excluded.summary,
               key_highlights_json = excluded.key_highlights_json, flags_json = excluded.flags_json,
               updated_at = datetime('now')""",
        (
            candidate_id,
            result["score"],
            result["summary"],
            json.dumps(result["key_highlights"]),
            json.dumps(result["flags"]),
        ),
    )


def backfill_resume_screening_round_results() -> int:
    """One-time-safe backfill for candidates scored before round_results existed (or
    before this bridge was wired up): for every job's latest rubric, (re)write
    round_results for every candidate with criterion_scores under it. Idempotent —
    safe to call on every startup.
    """
    updated = 0
    with get_db() as conn:
        jobs = conn.execute("SELECT id FROM jobs").fetchall()
        for job in jobs:
            job_id = job["id"]
            rubric_row = conn.execute(
                "SELECT id, version, criteria_json FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if rubric_row is None:
                continue
            rubric = Rubric(
                version=rubric_row["version"],
                criteria=[Criterion(**c) for c in json.loads(rubric_row["criteria_json"])],
            )
            candidate_ids = [
                row["candidate_id"]
                for row in conn.execute(
                    "SELECT DISTINCT candidate_id FROM criterion_scores WHERE rubric_id = ?", (rubric_row["id"],)
                ).fetchall()
            ]
            for candidate_id in candidate_ids:
                _upsert_resume_screening_round_result(conn, candidate_id, rubric_row["id"], rubric)
                updated += 1
        conn.commit()
    return updated


def _criteria_block(criteria: list[Criterion]) -> str:
    return "\n\n".join(f"- id: {c.id}\n  name: {c.name}\n  description: {c.description}" for c in criteria)


async def score_candidate(
    resume_text: str,
    rubric: Rubric,
    job_title: str = "",
    jd_text: str = "",
    only_criteria: list[str] | None = None,
) -> ScoreSheet:
    """Score one candidate against `rubric` in a single LLM call covering every requested
    criterion, plus a seniority-mismatch ("overqualified") judgment against `job_title`/`jd_text`.
    """
    criteria = rubric.criteria
    if only_criteria is not None:
        wanted = set(only_criteria)
        criteria = [c for c in criteria if c.id in wanted]

    prompt = SCORING_PROMPT.format(
        job_title=job_title or "this role",
        criteria_block=_criteria_block(criteria),
        jd_text=jd_text or "(not available)",
        resume_text=resume_text,
    )
    sheet = await call_structured(prompt, ScoreSheet, purpose="score_candidate")
    return sheet.validate_criteria([c.id for c in criteria])


async def score_pool(job_id: int, rubric_id: int, only_criteria: list[str] | None = None) -> None:
    """Score every resume-parsed candidate in a job against `rubric_id`.

    One candidate's failure never aborts the batch — each is scored independently and
    lands on status SCORED or ERROR (with reason) regardless of what happens to the others.

    Selective re-score (`only_criteria` set): carries forward every other criterion's score
    from the immediately preceding rubric version untouched, and only asks the LLM to
    (re)score the changed/added criteria — every rubric version still ends with a
    complete score set per candidate.
    """
    with get_db() as conn:
        rubric_row = conn.execute(
            "SELECT version, criteria_json FROM rubrics WHERE id = ? AND job_id = ?",
            (rubric_id, job_id),
        ).fetchone()
        if rubric_row is None:
            raise ValueError(f"rubric {rubric_id} not found for job {job_id}")

        rubric = Rubric(
            version=rubric_row["version"],
            criteria=[Criterion(**c) for c in json.loads(rubric_row["criteria_json"])],
        )

        job_row = conn.execute("SELECT title, jd_text FROM jobs WHERE id = ?", (job_id,)).fetchone()
        job_title = job_row["title"] if job_row else ""
        jd_text = job_row["jd_text"] if job_row else ""

        candidates = [
            dict(r)
            for r in conn.execute(
                "SELECT id, resume_text FROM candidates WHERE job_id = ? AND resume_text IS NOT NULL",
                (job_id,),
            ).fetchall()
        ]

        previous_rubric_id = None
        if only_criteria:
            prev_row = conn.execute(
                "SELECT id FROM rubrics WHERE job_id = ? AND version = ?",
                (job_id, rubric.version - 1),
            ).fetchone()
            previous_rubric_id = prev_row["id"] if prev_row else None

    carry_forward_ids = (
        [c.id for c in rubric.criteria if c.id not in set(only_criteria)] if only_criteria else []
    )

    async def _score_one(candidate: dict) -> None:
        candidate_id = candidate["id"]
        with get_db() as conn:
            conn.execute("UPDATE candidates SET status = 'SCORING' WHERE id = ?", (candidate_id,))
            conn.commit()

        try:
            if carry_forward_ids and previous_rubric_id is not None:
                with get_db() as conn:
                    placeholders = ",".join("?" * len(carry_forward_ids))
                    conn.execute(
                        f"""INSERT OR IGNORE INTO criterion_scores
                                (candidate_id, rubric_id, criterion_id, score, evidence, note)
                            SELECT candidate_id, ?, criterion_id, score, evidence, note
                            FROM criterion_scores
                            WHERE candidate_id = ? AND rubric_id = ? AND criterion_id IN ({placeholders})""",
                        (rubric_id, candidate_id, previous_rubric_id, *carry_forward_ids),
                    )
                    conn.commit()

            sheet = await score_candidate(
                candidate["resume_text"], rubric, job_title, jd_text, only_criteria=only_criteria
            )

            with get_db() as conn:
                for s in sheet.scores:
                    conn.execute(
                        """INSERT INTO criterion_scores
                               (candidate_id, rubric_id, criterion_id, score, evidence, note)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(candidate_id, rubric_id, criterion_id) DO UPDATE SET
                               score = excluded.score, evidence = excluded.evidence, note = excluded.note""",
                        (candidate_id, rubric_id, s.criterion_id, s.score, s.evidence, s.note),
                    )
                conn.execute(
                    "UPDATE candidates SET is_overqualified = ?, overqualification_reason = ? WHERE id = ?",
                    (int(sheet.is_overqualified), sheet.overqualification_reason or None, candidate_id),
                )
                conn.execute(
                    "UPDATE candidates SET status = 'SCORED', error_reason = NULL WHERE id = ?",
                    (candidate_id,),
                )
                _upsert_resume_screening_round_result(conn, candidate_id, rubric_id, rubric)
                conn.commit()
        except Exception as exc:  # noqa: BLE001 - isolate this candidate's failure from the batch
            with get_db() as conn:
                conn.execute(
                    "UPDATE candidates SET status = 'ERROR', error_reason = ? WHERE id = ?",
                    (str(exc), candidate_id),
                )
                conn.commit()

    await asyncio.gather(*(_score_one(c) for c in candidates))


async def _parse_and_extract_profile(job_id: int, candidate: dict) -> None:
    candidate_id = candidate["id"]
    try:
        path = storage.candidates_dir(job_id) / candidate["resume_path"]
        text = parser.extract_text(str(path))
        profile = await extract_profile(text)
        with get_db() as conn:
            conn.execute(
                "UPDATE candidates SET resume_text = ?, profile_json = ? WHERE id = ?",
                (text, profile.model_dump_json(), candidate_id),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - isolate this candidate's failure from the batch
        with get_db() as conn:
            conn.execute(
                "UPDATE candidates SET status = 'ERROR', error_reason = ? WHERE id = ?",
                (str(exc), candidate_id),
            )
            conn.commit()


async def scan_and_score_pool(job_id: int, rubric_id: int) -> None:
    """Background-task entry point for the "Start resume scanning" action.

    For every candidate with a CV on file but no resume_text yet: extract the resume
    text and profile (each candidate's failure is isolated, same as score_pool). Then
    scores the whole pool against `rubric_id`. Candidates that already have resume_text
    (e.g. re-running a scan) are left alone and go straight to scoring.
    """
    with get_db() as conn:
        pending = [
            dict(r)
            for r in conn.execute(
                """SELECT id, resume_path FROM candidates
                   WHERE job_id = ? AND resume_path IS NOT NULL AND resume_text IS NULL""",
                (job_id,),
            ).fetchall()
        ]

    await asyncio.gather(*(_parse_and_extract_profile(job_id, c) for c in pending))
    await score_pool(job_id, rubric_id)
