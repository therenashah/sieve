"""HR's natural-language candidate filters -> structured FilterSet -> safe SQL / post-rank filtering.

Safety model: the LLM only ever selects field/op/value from FilterSet's closed enums (see
models.py). SQL text itself always comes from the hardcoded _FIELD_SQL mapping below, never
from the LLM — values are always bound parameters.
"""

from app.db import get_db
from app.llm.client import call_structured
from app.llm.prompts import NL_FILTER_PROMPT
from app.models import Filter, FilterSet, Rubric


def _criteria_block(rubric: Rubric) -> str:
    return "\n".join(f"- {c.id}: {c.name}" for c in rubric.criteria)


async def parse_nl(text: str, rubric: Rubric, statuses: list[str]) -> FilterSet:
    prompt = NL_FILTER_PROMPT.format(
        statuses=", ".join(statuses),
        criteria_block=_criteria_block(rubric),
        text=text,
    )
    return await call_structured(prompt, FilterSet, purpose="parse_nl_filter")


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
        if f.field == "status" and f.op == "in":
            values = f.value if isinstance(f.value, list) else [f.value]
            clauses.append(f"status IN ({','.join('?' * len(values))})")
            params.extend(values)
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
