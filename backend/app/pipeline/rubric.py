"""Rubric generation, copilot-assisted editing, diff/apply, all per JD."""

from pydantic import BaseModel

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
    raise NotImplementedError


def apply_rubric(job_id: int, proposed: Rubric) -> ApplyResult:
    raise NotImplementedError
