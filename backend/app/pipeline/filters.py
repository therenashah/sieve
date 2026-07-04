"""HR's natural-language candidate filters -> structured FilterSet -> safe SQL / post-rank filtering.

Safety model: the LLM only ever selects field/op/value from FilterSet's closed enums (see
models.py). SQL text itself always comes from the hardcoded _FIELD_SQL mapping below, never
from the LLM — values are always bound parameters.
"""

import json

from app.db import get_db
from app.llm.client import call_structured
from app.llm.prompts import NL_FILTER_PROMPT
from app.models import Filter, FilterSet, Rubric

# Manually-addable "years of experience" checkbox buckets shown on the resume-screening
# filter panel. Selecting several is an OR (any bucket matches); combined with other facets
# via AND. max=None means "and up".
EXPERIENCE_BUCKETS = [
    {"key": "0-2", "label": "0–2 years", "min": 0, "max": 2},
    {"key": "2-5", "label": "2–5 years", "min": 2, "max": 5},
    {"key": "5-8", "label": "5–8 years", "min": 5, "max": 8},
    {"key": "8+", "label": "8+ years", "min": 8, "max": None},
]
_BUCKET_BY_KEY = {b["key"]: b for b in EXPERIENCE_BUCKETS}


def _criteria_block(rubric: Rubric) -> str:
    return "\n".join(f"- {c.id}: {c.name}" for c in rubric.criteria)


async def parse_nl(text: str, rubric: Rubric, statuses: list[str], job_title: str = "", jd_text: str = "") -> FilterSet:
    prompt = NL_FILTER_PROMPT.format(
        statuses=", ".join(statuses),
        criteria_block=_criteria_block(rubric),
        text=text,
        job_title=job_title or "(untitled role)",
        jd_text=jd_text or "(not available)",
    )
    return await call_structured(prompt, FilterSet, purpose="parse_nl_filter")


def facets(job_id: int) -> dict:
    """Candidate-derived values for the manually-addable checkbox filters: every distinct
    location on file, and the most common skills across this job's candidate pool (so the
    checkboxes always reflect real data instead of a generic hardcoded list).
    """
    with get_db() as conn:
        rows = conn.execute("SELECT profile_json FROM candidates WHERE job_id = ?", (job_id,)).fetchall()

    locations: dict[str, str] = {}
    skill_counts: dict[str, int] = {}
    for row in rows:
        profile = json.loads(row["profile_json"] or "{}")
        location = str(profile.get("location") or "").strip()
        if location:
            locations.setdefault(location.lower(), location)
        for skill in profile.get("skills") or []:
            skill = str(skill).strip()
            if skill:
                skill_counts[skill.lower()] = skill_counts.get(skill.lower(), 0) + 1

    top_skills = [skill for skill, _ in sorted(skill_counts.items(), key=lambda kv: -kv[1])[:12]]
    return {
        "locations": sorted(locations.values(), key=str.lower),
        "skills": top_skills,
        "experience_buckets": [{"key": b["key"], "label": b["label"]} for b in EXPERIENCE_BUCKETS],
    }


_FIELD_SQL: dict[tuple[str, str], str] = {
    ("location", "eq"): "lower(json_extract(profile_json, '$.location')) = lower(?)",
    ("location", "neq"): "lower(json_extract(profile_json, '$.location')) != lower(?)",
    ("location", "contains"): "lower(json_extract(profile_json, '$.location')) LIKE '%' || lower(?) || '%'",
    ("total_experience_years", "eq"): "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) = ?",
    ("total_experience_years", "neq"): "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) != ?",
    ("total_experience_years", "gte"): "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) >= ?",
    ("total_experience_years", "lte"): "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) <= ?",
    ("skills", "contains"): (
        "EXISTS (SELECT 1 FROM json_each(candidates.profile_json, '$.skills') WHERE value = lower(?))"
    ),
    ("education", "contains"): (
        "EXISTS (SELECT 1 FROM json_each(candidates.profile_json, '$.education') "
        "WHERE lower(value) LIKE '%' || lower(?) || '%')"
    ),
    ("current_company", "eq"): "lower(json_extract(profile_json, '$.current_company')) = lower(?)",
    ("current_company", "neq"): "lower(json_extract(profile_json, '$.current_company')) != lower(?)",
    ("current_company", "contains"): "lower(json_extract(profile_json, '$.current_company')) LIKE '%' || lower(?) || '%'",
    ("status", "eq"): "status = ?",
}

_RANK_DERIVED_FIELDS = {"overall", "criterion_score"}


def execute(job_id: int, fs: FilterSet) -> list[int]:
    """Candidate ids matching every SQL-expressible filter in `fs` (AND-combined, NULLs never match).

    "overall"/"criterion_score" filters are skipped here — they're derived from ranking and
    applied afterward via `apply_rank_filters`: execute() -> ranker.rank(ids) -> apply_rank_filters().
    """
    clauses: list[str] = []
    params: list = []

    for f in fs.filters:
        if f.field in _RANK_DERIVED_FIELDS:
            continue
        if f.op == "in":
            values = f.value if isinstance(f.value, list) else [f.value]
            if not values:
                continue
            if f.field == "status":
                clauses.append(f"status IN ({','.join('?' * len(values))})")
                params.extend(values)
            elif f.field == "location":
                clauses.append(
                    "(" + " OR ".join(["lower(json_extract(profile_json, '$.location')) = lower(?)"] * len(values)) + ")"
                )
                params.extend(values)
            elif f.field == "current_company":
                clauses.append(
                    "("
                    + " OR ".join(["lower(json_extract(profile_json, '$.current_company')) = lower(?)"] * len(values))
                    + ")"
                )
                params.extend(values)
            elif f.field == "skills":
                clauses.append(
                    "("
                    + " OR ".join(
                        ["EXISTS (SELECT 1 FROM json_each(candidates.profile_json, '$.skills') WHERE value = lower(?))"]
                        * len(values)
                    )
                    + ")"
                )
                params.extend(values)
            elif f.field == "experience_bucket":
                bucket_clauses = []
                for key in values:
                    bucket = _BUCKET_BY_KEY.get(key)
                    if bucket is None:
                        continue
                    if bucket["max"] is None:
                        bucket_clauses.append(
                            "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) >= ?"
                        )
                        params.append(bucket["min"])
                    else:
                        bucket_clauses.append(
                            "CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) >= ? "
                            "AND CAST(json_extract(profile_json, '$.total_experience_years') AS REAL) < ?"
                        )
                        params.extend([bucket["min"], bucket["max"]])
                if bucket_clauses:
                    clauses.append("(" + " OR ".join(bucket_clauses) + ")")
            else:
                raise ValueError(f"unsupported field for op 'in': {f.field}")
            continue
        sql = _FIELD_SQL.get((f.field, f.op))
        if sql is None:
            raise ValueError(f"unsupported field/op combination: {f.field}/{f.op}")
        clauses.append(sql)
        params.append(f.value)

    where = " AND ".join(clauses) if clauses else "1=1"
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id FROM candidates WHERE job_id = ? AND ({where})", (job_id, *params)
        ).fetchall()
    return [row["id"] for row in rows]


def _compare(actual, op: str, expected) -> bool:
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "gte":
        return actual >= expected
    if op == "lte":
        return actual <= expected
    raise ValueError(f"unsupported op for a ranked-value filter: {op}")


def _matches_criterion_filter(candidate: dict, f: Filter) -> bool:
    scores = candidate["scores"]
    if f.criterion_id is not None:
        scores = [s for s in scores if s["criterion_id"] == f.criterion_id]

    if f.op == "exists":
        has_evidence = any(s["evidence"] != "not found" for s in scores)
        return has_evidence if f.value else not has_evidence

    return any(_compare(s["score"], f.op, f.value) for s in scores)


def apply_rank_filters(ranked: list[dict], fs: FilterSet) -> list[dict]:
    """Apply "overall"/"criterion_score" filters to an already-ranked list (from ranker.rank)."""
    result = ranked
    for f in fs.filters:
        if f.field == "overall":
            result = [c for c in result if _compare(c["overall"], f.op, f.value)]
        elif f.field == "criterion_score":
            result = [c for c in result if _matches_criterion_filter(c, f)]
    return result
