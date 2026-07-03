"""Weighted ranking of scored candidates (plain arithmetic, no LLM)."""

import json

from app.db import get_db


def rank(job_id: int, rubric_id: int, candidate_ids: list[int] | None = None) -> list[dict]:
    """Rank candidates by weighted score under `rubric_id`. No LLM calls.

    Returns candidates sorted desc by `overall` (0..1): [{candidate_id, name, overall,
    status, scores: [{criterion_id, score, evidence}]}]. Candidates with no scores yet
    under this rubric_id come back with overall=0 and an empty scores list.
    """
    with get_db() as conn:
        rubric_row = conn.execute(
            "SELECT criteria_json FROM rubrics WHERE id = ? AND job_id = ?", (rubric_id, job_id)
        ).fetchone()
        if rubric_row is None:
            raise ValueError(f"rubric {rubric_id} not found for job {job_id}")
        weights = {c["id"]: c["weight"] for c in json.loads(rubric_row["criteria_json"])}

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ",".join("?" * len(candidate_ids))
            cand_rows = conn.execute(
                f"SELECT id, name, status FROM candidates WHERE job_id = ? AND id IN ({placeholders})",
                (job_id, *candidate_ids),
            ).fetchall()
        else:
            cand_rows = conn.execute(
                "SELECT id, name, status FROM candidates WHERE job_id = ?", (job_id,)
            ).fetchall()

        candidates = {
            row["id"]: {"candidate_id": row["id"], "name": row["name"], "status": row["status"], "scores": []}
            for row in cand_rows
        }

        score_rows = []
        if candidates:
            score_placeholders = ",".join("?" * len(candidates))
            score_rows = conn.execute(
                f"""SELECT candidate_id, criterion_id, score, evidence FROM criterion_scores
                    WHERE rubric_id = ? AND candidate_id IN ({score_placeholders})""",
                (rubric_id, *candidates.keys()),
            ).fetchall()

    for row in score_rows:
        candidates[row["candidate_id"]]["scores"].append(
            {"criterion_id": row["criterion_id"], "score": row["score"], "evidence": row["evidence"]}
        )

    results = [
        {**candidate, "overall": sum(s["score"] * weights.get(s["criterion_id"], 0.0) for s in candidate["scores"]) / 10}
        for candidate in candidates.values()
    ]
    results.sort(key=lambda c: c["overall"], reverse=True)
    return results
