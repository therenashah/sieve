"""Rubric generation, copilot-assisted editing, diff/apply, all per JD."""

import json

from pydantic import BaseModel

from app.db import get_db
from app.llm.client import PipelineLLMError, call_structured
from app.llm.prompts import RUBRIC_PROMPT
from app.models import ApplyResult, Criterion, Rubric, RubricDiff


class _RubricDraft(BaseModel):
    """LLM-facing shape for generate_rubric: no `version`, weight gets overridden below."""

    criteria: list[Criterion]


async def generate_rubric(jd_text: str) -> Rubric:
    """Extract criteria and LLM-judged weights from the JD.

    The LLM assigns weights based on emphasis in the JD (e.g. a "must have" requirement
    becomes a higher-weight criterion). `Rubric`'s own validator auto-normalizes if the
    weights don't sum to exactly 1.0, and hard-fails on any negative weight.
    """
    draft = await call_structured(
        RUBRIC_PROMPT.format(jd_text=jd_text),
        _RubricDraft,
        purpose="generate_rubric",
    )
    if not draft.criteria:
        raise PipelineLLMError("LLM returned zero criteria for this job description")

    return Rubric(version=1, criteria=draft.criteria)


async def propose_update(current: Rubric, hr_prompt: str) -> Rubric:
    raise NotImplementedError


def diff(old: Rubric, new: Rubric) -> RubricDiff:
    old_by_id = {c.id: c for c in old.criteria}
    new_by_id = {c.id: c for c in new.criteria}

    weight_changes = [
        (cid, old_by_id[cid].weight, new_by_id[cid].weight)
        for cid in old_by_id
        if cid in new_by_id and old_by_id[cid].weight != new_by_id[cid].weight
    ]
    added = [c for cid, c in new_by_id.items() if cid not in old_by_id]
    removed = [cid for cid in old_by_id if cid not in new_by_id]
    edited_descriptions = [
        cid
        for cid in old_by_id
        if cid in new_by_id and old_by_id[cid].description != new_by_id[cid].description
    ]

    return RubricDiff(
        weight_changes=weight_changes,
        added=added,
        removed=removed,
        edited_descriptions=edited_descriptions,
    )


def apply_rubric(job_id: int, proposed: Rubric) -> ApplyResult:
    with get_db() as conn:
        row = conn.execute(
            "SELECT version, criteria_json FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1",
            (job_id,),
        ).fetchone()

        if row is None:
            new_version = 1
            rescore_criterion_ids = [c.id for c in proposed.criteria]
        else:
            current = Rubric(
                version=row["version"],
                criteria=[Criterion(**c) for c in json.loads(row["criteria_json"])],
            )
            new_version = current.version + 1
            d = diff(current, proposed)
            rescore_criterion_ids = [c.id for c in d.added] + d.edited_descriptions

        conn.execute(
            "INSERT INTO rubrics (job_id, version, criteria_json) VALUES (?, ?, ?)",
            (job_id, new_version, json.dumps([c.model_dump() for c in proposed.criteria])),
        )
        conn.commit()

    return ApplyResult(new_version=new_version, rescore_criterion_ids=rescore_criterion_ids)


async def generate_and_apply_rubric(job_id: int, jd_text: str) -> None:
    """Background-task entry point: generate the rubric for a job's JD and persist it.

    Errors are swallowed (logged) rather than raised, since this runs after the
    triggering HTTP request has already returned a response.
    """
    try:
        rubric = await generate_rubric(jd_text)
        apply_rubric(job_id, rubric)
    except Exception as exc:  # noqa: BLE001 - background task, nothing left to propagate to
        print(f"[generate_and_apply_rubric] job_id={job_id} failed: {exc}")
