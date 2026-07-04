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
    # Seniority-mismatch flag: candidate's recent experience reads as MORE senior than
    # this role, not just "very qualified". Recomputed on every scoring call (including
    # selective re-scores) since it's part of the same LLM response, not a separate call.
    is_overqualified: bool = False
    overqualification_reason: str = ""

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


class FilterParseRequest(BaseModel):
    text: str


class RubricChatRequest(BaseModel):
    message: str
    proposed_rubric: Rubric | None = None  # a prior in-session proposal to keep iterating on


class RoundAIConfig(BaseModel):
    """What the AI interviewer bot for this round is given/asked to do. Stored as-is
    (not just UI decoration) — the interview engine reads this directly to decide what
    context to share, how long to run, how to behave, and what to produce afterward."""

    # What context to share with the interviewer
    share_jd: bool = True
    share_profile: bool = True
    share_resume: bool = True
    share_previous_rounds: bool = True
    share_rubric: bool = True
    instructions: str = ""

    # How the interview runs
    duration_minutes: int = 30           # approximate target length; drives the timer + wrap-up
    difficulty: Literal["easy", "balanced", "hard"] = "balanced"
    focus_areas: str = ""                # optional free-text emphasis ("system design, ownership")
    allow_candidate_questions: bool = True  # brief candidate Q&A before wrapping up

    # Outcome & evaluation
    store_transcript: bool = True
    store_recording: bool = False        # candidate video/audio recorded via the browser for proctoring
    generate_scorecard: bool = True
    flag_inconsistencies: bool = True

    @field_validator("duration_minutes")
    @classmethod
    def _clamp_duration(cls, v: int) -> int:
        return max(5, min(90, v))


class AddRoundRequest(BaseModel):
    template_key: str  # one of the ROUND_TEMPLATES keys ("custom" mints a fresh round_key)
    name: str | None = None  # required override when template_key == "custom"
    description: str | None = None


class UpdateRoundRequest(BaseModel):
    name: str
    description: str = ""
    is_ai_based: bool = False
    ai_config: RoundAIConfig | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


class TriggerScreeningRequest(BaseModel):
    question_ids: list[int] = Field(default_factory=list)


class ExportCandidatesRequest(BaseModel):
    candidate_ids: list[int]


class TriggerScreeningResponse(BaseModel):
    token: str
    chat_url: str
    expires_at: str


class AddQuestionRequest(BaseModel):
    question_text: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatTurnResponse(BaseModel):
    session_status: str  # active | completed | expired
    phase: str
    messages: list[ChatMessage]


class ChatMessageRequest(BaseModel):
    message: str


class SessionStatusResponse(BaseModel):
    session_status: str
    phase: str
    candidate_name: str
    job_title: str
    messages: list[ChatMessage]


# --- AI interview round ------------------------------------------------------


class TriggerInterviewRequest(BaseModel):
    round_key: str  # which AI-based round on the job this interview is for


class TriggerInterviewResponse(BaseModel):
    token: str
    interview_url: str
    expires_at: str


class ScheduleInterviewRequest(BaseModel):
    slot: str  # ISO datetime chosen from the offered slots


class InterviewMessageRequest(BaseModel):
    message: str


class ProctorEventRequest(BaseModel):
    type: str          # e.g. "tab_hidden" | "tab_visible" | "camera_off" | "no_face"
    detail: str = ""


class InterviewTurnMessage(BaseModel):
    role: str          # assistant | candidate
    content: str
    audio_b64: str | None = None  # base64 mp3 of the assistant turn (None -> browser TTS)


class InterviewTurnResponse(BaseModel):
    status: str        # invited | scheduled | in_progress | completed | expired
    phase: str         # INTRO | INTERVIEW | WRAPUP | ENDED
    messages: list[InterviewTurnMessage]
    remaining_seconds: int | None = None   # until the hard stop, once started
    should_wrap_up: bool = False


class InterviewStatusResponse(BaseModel):
    status: str
    phase: str
    candidate_name: str
    job_title: str
    round_name: str
    instructions: str
    duration_minutes: int
    store_recording: bool
    allow_candidate_questions: bool
    scheduled_at: str | None = None
    expires_at: str
    slots: list[str] = Field(default_factory=list)          # offered scheduling slots (when unscheduled)
    messages: list[InterviewTurnMessage] = Field(default_factory=list)  # transcript (when in progress)
    remaining_seconds: int | None = None
