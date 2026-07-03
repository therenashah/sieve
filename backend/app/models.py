"""All Pydantic models for the app live here, shared across pipeline/conversations/api."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    status: str = "ok"
    app_env: str


class Criterion(BaseModel):
    id: str  # "c1", "c2"... stable across rubric versions
    name: str
    description: str  # must include 3/6/9 score anchors
    weight: float  # 0..1


class Rubric(BaseModel):
    version: int
    criteria: list[Criterion]

    @model_validator(mode="after")
    def _validate_weights(self) -> "Rubric":
        if any(c.weight < 0 for c in self.criteria):
            raise ValueError("criterion weights must not be negative")
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 0.01:
            if total <= 0:
                raise ValueError("criterion weights must sum to a positive value")
            for c in self.criteria:
                c.weight = c.weight / total
        return self


class Profile(BaseModel):
    name: str | None = None
    email: str | None = None
    location: str | None = None  # normalized city ("Mumbai")
    total_experience_years: float | None = None
    skills: list[str] = Field(default_factory=list)  # lowercase, deduped, <=30
    education: list[str] = Field(default_factory=list)
    current_company: str | None = None
    notice_period: str | None = None

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for skill in v:
            normalized = skill.strip().lower()
            if normalized and normalized not in seen:
                seen.append(normalized)
        return seen[:30]


class CriterionScore(BaseModel):
    criterion_id: str
    score: int  # 0..10, clamped
    evidence: str  # verbatim resume quote or "not found"
    note: str = ""

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))


class ScoreSheet(BaseModel):
    scores: list[CriterionScore]

    def validate_criteria(self, expected_ids: list[str]) -> "ScoreSheet":
        actual_ids = [s.criterion_id for s in self.scores]
        if len(actual_ids) != len(set(actual_ids)):
            raise ValueError("ScoreSheet contains duplicate criterion_id entries")
        if set(actual_ids) != set(expected_ids):
            missing = set(expected_ids) - set(actual_ids)
            extra = set(actual_ids) - set(expected_ids)
            raise ValueError(
                f"ScoreSheet does not match expected criteria: missing={sorted(missing)}, extra={sorted(extra)}"
            )
        return self


class Filter(BaseModel):
    field: Literal[
        "location",
        "total_experience_years",
        "skills",
        "education",
        "current_company",
        "status",
        "overall",
        "criterion_score",
    ]
    op: Literal["eq", "neq", "gte", "lte", "contains", "in", "exists"]
    value: str | float | bool | list
    criterion_id: str | None = None
    # criterion_id required for field=="criterion_score" UNLESS op=="exists", where
    # omitting it means "any criterion in the rubric" (evidence-presence check across all)

    @model_validator(mode="after")
    def _validate_field_op_compatibility(self) -> "Filter":
        if self.field != "criterion_score" and self.criterion_id is not None:
            raise ValueError("criterion_id is only valid when field is 'criterion_score'")
        if self.field == "criterion_score" and self.op != "exists" and self.criterion_id is None:
            raise ValueError("criterion_id is required for field 'criterion_score' unless op is 'exists'")
        if self.op == "exists":
            if self.field != "criterion_score":
                raise ValueError("op 'exists' is only valid for field 'criterion_score'")
            if not isinstance(self.value, bool):
                raise ValueError("op 'exists' requires a boolean value")
        if self.op in ("gte", "lte") and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError(f"op '{self.op}' requires a numeric value")
        if self.op == "contains" and not isinstance(self.value, (list, str)):
            raise ValueError("op 'contains' requires a list or string value")
        return self


class FilterSet(BaseModel):
    filters: list[Filter]
    unparsed: list[str] = Field(default_factory=list)  # NL fragments that couldn't be mapped


class RubricDiff(BaseModel):
    weight_changes: list[tuple[str, float, float]]  # (criterion_id, old, new)
    added: list[Criterion]
    removed: list[str]
    edited_descriptions: list[str]


class ApplyResult(BaseModel):
    new_version: int
    rescore_criterion_ids: list[str]  # added + edited_descriptions
