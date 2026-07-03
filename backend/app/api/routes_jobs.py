"""Jobs, JD/tracker/CV uploads, candidates. Everything here is recruiter-only."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app import storage, tracker
from app.auth import require_auth
from app.config import get_settings
from app.conversations import engine
from app.conversations import interview as interview_engine
from app.db import BUILTIN_ROUNDS, DEFAULT_HR_QUESTIONS, ROUND_TEMPLATES, get_db
from app.models import (
    AddQuestionRequest,
    AddRoundRequest,
    Criterion,
    FilterParseRequest,
    FilterSet,
    RoundAIConfig,
    Rubric,
    RubricChatRequest,
    TriggerInterviewRequest,
    TriggerInterviewResponse,
    TriggerScreeningRequest,
    TriggerScreeningResponse,
    UpdateRoundRequest,
)
from app.pipeline import filters, hr_questions, parser, ranker, rubric, scorer

_CANDIDATE_STATUSES = ["PARSING", "SCORING", "SCORED", "ERROR"]


def _get_latest_rubric(job_id: int) -> Rubric | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT version, criteria_json FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return Rubric(version=row["version"], criteria=[Criterion(**c) for c in json.loads(row["criteria_json"])])

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_auth)])


def _get_job_or_404(job_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return dict(row)


@router.get("")
async def list_jobs():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT j.id, j.title, j.description, j.status, j.jd_filename, j.created_at,
                      COUNT(c.id) AS candidate_count,
                      SUM(CASE WHEN c.resume_path IS NOT NULL THEN 1 ELSE 0 END) AS cvs_matched
               FROM jobs j LEFT JOIN candidates c ON c.job_id = j.id
               GROUP BY j.id
               ORDER BY j.id DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("", status_code=201)
async def create_job(title: str = Form(...), description: str = Form("")):
    title = title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Job title is required")

    with get_db() as conn:
        cur = conn.execute("INSERT INTO jobs (title, description) VALUES (?, ?)", (title, description.strip()))
        job_id = cur.lastrowid
        for index, question in enumerate(DEFAULT_HR_QUESTIONS):
            conn.execute(
                """INSERT INTO job_questions (job_id, question_text, order_index, is_mandatory, source)
                   VALUES (?, ?, ?, 1, 'default')""",
                (job_id, question, index),
            )
        for index, round_def in enumerate(BUILTIN_ROUNDS):
            conn.execute(
                """INSERT INTO job_rounds (job_id, round_key, name, description, order_index, is_builtin)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (job_id, round_def["round_key"], round_def["name"], round_def["description"], index),
            )
        conn.commit()

    storage.job_dir(job_id)  # create the storage folder immediately, before any upload happens
    return _get_job_or_404(job_id)


@router.get("/{job_id}")
async def get_job(job_id: int):
    return _get_job_or_404(job_id)


@router.post("/{job_id}/jd")
async def upload_jd(job_id: int, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Saves the JD file, extracts its text, and kicks off rubric generation in the
    background (an LLM call) so this endpoint returns quickly. Note: only .pdf and
    .docx have a text extractor (see pipeline/parser.py) — a .doc upload will save
    fine here but fail extraction, so rubric generation won't run for it.
    """
    _get_job_or_404(job_id)
    if not file.filename or not file.filename.lower().endswith((".pdf", ".doc", ".docx")):
        raise HTTPException(status_code=400, detail="Job description must be a PDF or Word document")

    content = await file.read()
    filename, path = storage.save_jd_file(job_id, file.filename, content)

    try:
        jd_text = parser.extract_text(str(path))
    except parser.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read that file: {exc}") from exc

    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET jd_filename = ?, jd_path = ?, jd_text = ?, status = 'active' WHERE id = ?",
            (filename, str(path), jd_text, job_id),
        )
        conn.commit()

    background_tasks.add_task(rubric.generate_and_apply_rubric, job_id, jd_text)
    background_tasks.add_task(hr_questions.generate_and_apply_hr_questions, job_id, jd_text)

    return {"jd_filename": filename}


@router.post("/{job_id}/tracker")
async def upload_tracker(job_id: int, file: UploadFile = File(...)):
    _get_job_or_404(job_id)
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Candidate tracker must be a .csv or .xlsx file")

    content = await file.read()
    try:
        rows, errors = tracker.parse_tracker(file.filename, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read that file: {exc}") from exc

    with get_db() as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO candidates (
                       job_id, name, email, phone, external_id, match_score, overall_status,
                       recruiter, tags, application_date, source_type, source_name,
                       ownership_status, shortlisting_status, resume_screening_status,
                       l1_status, l2_status, l3_status, pre_offer_status
                   ) VALUES (
                       :job_id, :name, :email, :phone, :external_id, :match_score, :overall_status,
                       :recruiter, :tags, :application_date, :source_type, :source_name,
                       :ownership_status, :shortlisting_status, :resume_screening_status,
                       :l1_status, :l2_status, :l3_status, :pre_offer_status
                   )
                   ON CONFLICT(job_id, external_id) DO UPDATE SET
                       name = excluded.name, email = excluded.email, phone = excluded.phone,
                       match_score = excluded.match_score, overall_status = excluded.overall_status,
                       recruiter = excluded.recruiter, tags = excluded.tags,
                       application_date = excluded.application_date, source_type = excluded.source_type,
                       source_name = excluded.source_name, ownership_status = excluded.ownership_status,
                       shortlisting_status = excluded.shortlisting_status,
                       resume_screening_status = excluded.resume_screening_status,
                       l1_status = excluded.l1_status, l2_status = excluded.l2_status,
                       l3_status = excluded.l3_status, pre_offer_status = excluded.pre_offer_status""",
                {**row, "job_id": job_id},
            )
        conn.commit()
        cand_rows = conn.execute(
            "SELECT * FROM candidates WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()

    return {"candidates": [dict(r) for r in cand_rows], "row_errors": errors, "count": len(cand_rows)}


@router.post("/{job_id}/cvs")
async def upload_cvs(job_id: int, file: UploadFile = File(...)):
    _get_job_or_404(job_id)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="CVs must be uploaded as a single .zip file")

    with get_db() as conn:
        cand_rows = conn.execute(
            "SELECT id, external_id, name FROM candidates WHERE job_id = ?", (job_id,)
        ).fetchall()
    candidates = [dict(r) for r in cand_rows]
    if not candidates:
        raise HTTPException(status_code=400, detail="Upload the candidate tracker before uploading CVs")

    content = await file.read()
    try:
        result = storage.process_cv_zip(job_id, content, candidates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_db() as conn:
        for m in result["matched"]:
            conn.execute("UPDATE candidates SET resume_path = ? WHERE id = ?", (m["file"], m["candidate_id"]))
        conn.commit()

    return result


@router.post("/{job_id}/scan")
async def scan_candidates(job_id: int, background_tasks: BackgroundTasks):
    """Kick off resume text extraction, profile extraction, and scoring (against the
    latest rubric) for this job's candidates. Runs in the background; poll
    GET /{job_id}/candidates for per-candidate status as it progresses."""
    _get_job_or_404(job_id)
    with get_db() as conn:
        rubric_row = conn.execute(
            "SELECT id FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1", (job_id,)
        ).fetchone()
    if rubric_row is None:
        raise HTTPException(status_code=400, detail="Generate a rubric before scanning candidates")

    background_tasks.add_task(scorer.scan_and_score_pool, job_id, rubric_row["id"])
    return {"status": "scanning", "rubric_id": rubric_row["id"]}


@router.post("/{job_id}/filters/parse")
async def parse_filters(job_id: int, payload: FilterParseRequest):
    """Translate HR's free-text filter request into a FilterSet, using the job's current
    rubric so criteria mentions ("strong kubernetes") map to the right criterion id. The
    frontend renders the result as chips and passes it back into GET /{job_id}/candidates."""
    _get_job_or_404(job_id)
    active_rubric = _get_latest_rubric(job_id)
    if active_rubric is None:
        raise HTTPException(status_code=400, detail="Generate a rubric before filtering candidates")

    return await filters.parse_nl(payload.text, active_rubric, _CANDIDATE_STATUSES)


def _summarize_diff(changes) -> str:
    parts = []
    if changes.added:
        parts.append(f"added {len(changes.added)} criteria: {', '.join(c.name for c in changes.added)}")
    if changes.removed:
        parts.append(f"removed {len(changes.removed)} criteria: {', '.join(changes.removed)}")
    if changes.edited_descriptions:
        parts.append(f"updated the description on {len(changes.edited_descriptions)} criteria")
    if changes.weight_changes:
        parts.append(f"reweighted {len(changes.weight_changes)} criteria")
    if not parts:
        return "I didn't make any changes to the rubric based on that."
    return "I " + "; ".join(parts) + ". Review below, then apply if this looks right."


@router.post("/{job_id}/rubric/chat")
async def rubric_chat(job_id: int, payload: RubricChatRequest):
    """Stateless rubric copilot turn: propose changes per HR's message, against either
    the persisted rubric or a prior in-session proposal the client is still holding.
    Nothing persists until POST /{job_id}/rubric/apply is called with the result."""
    _get_job_or_404(job_id)
    base_rubric = payload.proposed_rubric or _get_latest_rubric(job_id)
    if base_rubric is None:
        raise HTTPException(status_code=400, detail="Generate a rubric before using the copilot")

    proposed = await rubric.propose_update(base_rubric, payload.message)
    changes = rubric.diff(base_rubric, proposed)
    return {"reply": _summarize_diff(changes), "proposed_rubric": proposed, "diff": changes}


@router.get("/{job_id}/rubric")
async def get_rubric(job_id: int, version: int | None = None):
    """Latest rubric for this job, or a specific version. 404 if none generated yet
    (e.g. no JD uploaded, or generation is still running in the background)."""
    _get_job_or_404(job_id)
    with get_db() as conn:
        if version is not None:
            row = conn.execute(
                "SELECT version, criteria_json FROM rubrics WHERE job_id = ? AND version = ?",
                (job_id, version),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT version, criteria_json FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1",
                (job_id,),
            ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No rubric generated yet for this job")

    return {"version": row["version"], "criteria": json.loads(row["criteria_json"])}


@router.get("/{job_id}/questions")
async def list_questions(job_id: int):
    """The HR screening question pool for this job: generic defaults + JD-derived AI
    suggestions (generated in the background after JD upload) + anything the recruiter
    has added. This is what the trigger-screening modal shows for the recruiter to pick from.
    """
    _get_job_or_404(job_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM job_questions WHERE job_id = ? ORDER BY order_index ASC", (job_id,)
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/{job_id}/questions/generate")
async def generate_questions(job_id: int):
    """On-demand (synchronous) AI question generation from the job's stored JD text.

    Exists mainly for jobs whose JD was uploaded before AI-generated questions were
    wired into the JD-upload flow (or if that background task silently failed) — this
    lets the recruiter (re)generate from the trigger-screening modal without re-uploading
    the JD. Returns the full, refreshed question pool.
    """
    job = _get_job_or_404(job_id)
    jd_text = (job.get("jd_text") or "").strip()
    if not jd_text:
        raise HTTPException(status_code=400, detail="Upload a job description before generating questions")

    try:
        questions = await hr_questions.generate_hr_questions(jd_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't generate questions: {exc}") from exc

    hr_questions.add_questions(job_id, questions, source="ai")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM job_questions WHERE job_id = ? ORDER BY order_index ASC", (job_id,)
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/{job_id}/questions", status_code=201)
async def add_question(job_id: int, body: AddQuestionRequest):
    _get_job_or_404(job_id)
    text = body.question_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Question text is required")

    with get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM job_questions WHERE job_id = ?", (job_id,)
        ).fetchone()["m"]
        cur = conn.execute(
            """INSERT INTO job_questions (job_id, question_text, order_index, is_mandatory, source)
               VALUES (?, ?, ?, 1, 'custom')""",
            (job_id, text, max_order + 1),
        )
        conn.commit()
        question_id = cur.lastrowid
        row = conn.execute("SELECT * FROM job_questions WHERE id = ?", (question_id,)).fetchone()
    return dict(row)


@router.delete("/{job_id}/questions/{question_id}", status_code=204)
async def delete_question(job_id: int, question_id: int):
    _get_job_or_404(job_id)
    with get_db() as conn:
        conn.execute("DELETE FROM job_questions WHERE id = ? AND job_id = ?", (question_id, job_id))
        conn.commit()
    return None


def _parse_round(row) -> dict:
    round_ = dict(row)
    round_["is_builtin"] = bool(round_["is_builtin"])
    round_["is_ai_based"] = bool(round_["is_ai_based"])
    ai_config_json = round_.pop("ai_config_json")
    round_["ai_config"] = json.loads(ai_config_json) if ai_config_json else None
    return round_


def _default_ai_config(round_name: str, job_title: str) -> dict:
    return RoundAIConfig(
        instructions=(
            f"Conduct the {round_name} interview for the {job_title} role. Ask clear, structured "
            "questions based on the job description and the candidate's profile, probe for depth on "
            "vague or evasive answers, and stay professional and unbiased throughout."
        )
    ).model_dump()


@router.get("/{job_id}/rounds")
async def list_rounds(job_id: int):
    """The configured pipeline for this job, in order — resume_screening and hr_screening
    are always present (builtin); anything else is an optional round the recruiter added.
    """
    _get_job_or_404(job_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM job_rounds WHERE job_id = ? ORDER BY order_index ASC", (job_id,)
        ).fetchall()
    return [_parse_round(r) for r in rows]


@router.get("/{job_id}/rounds/templates")
async def list_round_templates(job_id: int):
    """Optional-round templates not yet added to this job (custom is always offered —
    a recruiter may want more than one custom round)."""
    _get_job_or_404(job_id)
    with get_db() as conn:
        existing_keys = {
            row["round_key"] for row in conn.execute("SELECT round_key FROM job_rounds WHERE job_id = ?", (job_id,))
        }
    return [t for t in ROUND_TEMPLATES if t["key"] == "custom" or t["key"] not in existing_keys]


@router.post("/{job_id}/rounds", status_code=201)
async def add_round(job_id: int, body: AddRoundRequest):
    job = _get_job_or_404(job_id)
    template = next((t for t in ROUND_TEMPLATES if t["key"] == body.template_key), None)
    if template is None:
        raise HTTPException(status_code=400, detail=f"Unknown round template '{body.template_key}'")

    name = (body.name or template["name"]).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Round name is required")
    description = body.description if body.description is not None else template["description"]

    with get_db() as conn:
        if body.template_key == "custom":
            existing_customs = conn.execute(
                "SELECT COUNT(*) AS c FROM job_rounds WHERE job_id = ? AND round_key LIKE 'custom_%'", (job_id,)
            ).fetchone()["c"]
            round_key = f"custom_{existing_customs + 1}"
        else:
            round_key = body.template_key
            clash = conn.execute(
                "SELECT 1 FROM job_rounds WHERE job_id = ? AND round_key = ?", (job_id, round_key)
            ).fetchone()
            if clash:
                raise HTTPException(status_code=400, detail=f"'{template['name']}' has already been added")

        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM job_rounds WHERE job_id = ?", (job_id,)
        ).fetchone()["m"]
        cur = conn.execute(
            """INSERT INTO job_rounds (job_id, round_key, name, description, order_index, is_builtin)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (job_id, round_key, name, description, max_order + 1),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM job_rounds WHERE id = ?", (cur.lastrowid,)).fetchone()

    result = _parse_round(row)
    result["default_ai_config"] = _default_ai_config(name, job["title"])
    return result


@router.put("/{job_id}/rounds/{round_id}")
async def update_round(job_id: int, round_id: int, body: UpdateRoundRequest):
    _get_job_or_404(job_id)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM job_rounds WHERE id = ? AND job_id = ?", (round_id, job_id)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Round not found")

        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Round name is required")

        ai_config = body.ai_config.model_dump() if (body.is_ai_based and body.ai_config) else None
        conn.execute(
            """UPDATE job_rounds SET name = ?, description = ?, is_ai_based = ?, ai_config_json = ?
               WHERE id = ?""",
            (name, body.description, int(body.is_ai_based), json.dumps(ai_config) if ai_config else None, round_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM job_rounds WHERE id = ?", (round_id,)).fetchone()
    return _parse_round(row)


@router.delete("/{job_id}/rounds/{round_id}", status_code=204)
async def delete_round(job_id: int, round_id: int):
    _get_job_or_404(job_id)
    with get_db() as conn:
        row = conn.execute(
            "SELECT is_builtin, round_key FROM job_rounds WHERE id = ? AND job_id = ?", (round_id, job_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Round not found")
        if row["is_builtin"]:
            raise HTTPException(status_code=400, detail="Built-in rounds can't be removed")
        conn.execute(
            """DELETE FROM round_results WHERE round = ? AND candidate_id IN
               (SELECT id FROM candidates WHERE job_id = ?)""",
            (row["round_key"], job_id),
        )
        conn.execute("DELETE FROM job_rounds WHERE id = ?", (round_id,))
        conn.commit()
    return None


@router.post("/{job_id}/rubric/apply")
async def apply_rubric_edit(job_id: int, proposed: Rubric, background_tasks: BackgroundTasks):
    """Persist a proposed rubric (manual HR edits, or a fine-tune chat proposal) as the
    next version. If candidates were already scanned, kicks off a selective re-score in
    the background for just the added/edited criteria — untouched criteria carry forward."""
    _get_job_or_404(job_id)
    result = rubric.apply_rubric(job_id, proposed)

    rescoring = False
    if result.rescore_criterion_ids:
        with get_db() as conn:
            has_scored_candidates = (
                conn.execute(
                    "SELECT 1 FROM candidates WHERE job_id = ? AND resume_text IS NOT NULL LIMIT 1",
                    (job_id,),
                ).fetchone()
                is not None
            )
            new_rubric_row = conn.execute(
                "SELECT id FROM rubrics WHERE job_id = ? AND version = ?", (job_id, result.new_version)
            ).fetchone()
        if has_scored_candidates and new_rubric_row:
            rescoring = True
            background_tasks.add_task(
                scorer.score_pool, job_id, new_rubric_row["id"], result.rescore_criterion_ids
            )

    return {
        "new_version": result.new_version,
        "rescore_criterion_ids": result.rescore_criterion_ids,
        "rescoring": rescoring,
    }


@router.get("/{job_id}/candidates")
async def list_candidates(job_id: int, filter: str | None = Query(default=None), version: int | None = None):
    """Candidates for this job, ranked against the rubric when one exists.

    `filter` is a URL-encoded FilterSet JSON (see POST /{job_id}/filters/parse to build
    one from natural language). Response shape: {rubric_version, candidates, unparsed}.
    """
    _get_job_or_404(job_id)

    with get_db() as conn:
        if version is not None:
            rubric_row = conn.execute(
                "SELECT id, version FROM rubrics WHERE job_id = ? AND version = ?", (job_id, version)
            ).fetchone()
        else:
            rubric_row = conn.execute(
                "SELECT id, version FROM rubrics WHERE job_id = ? ORDER BY version DESC LIMIT 1", (job_id,)
            ).fetchone()

        rows = conn.execute(
            "SELECT * FROM candidates WHERE job_id = ? ORDER BY match_score DESC, id ASC", (job_id,)
        ).fetchall()

    base_by_id: dict[int, dict] = {}
    order: list[int] = []
    for row in rows:
        candidate = dict(row)
        candidate["profile"] = json.loads(candidate.pop("profile_json"))
        screening_result_json = candidate.pop("screening_result_json")
        candidate["screening_result"] = json.loads(screening_result_json) if screening_result_json else None
        base_by_id[candidate["id"]] = candidate
        order.append(candidate["id"])

    fs: FilterSet | None = None
    unparsed: list[str] = []
    if filter:
        try:
            fs = FilterSet.model_validate_json(filter)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid filter: {exc}") from exc
        unparsed = fs.unparsed

    if rubric_row is None:
        # No rubric yet -- nothing to rank/score-filter with. Non-rank filters (location,
        # skills, etc.) still apply; overall/criterion_score filters are silently skipped.
        ids = filters.execute(job_id, fs) if fs else order
        id_set = set(ids)
        candidates = [{**base_by_id[cid], "overall": None, "scores": []} for cid in order if cid in id_set]
        return {"rubric_version": None, "candidates": candidates, "unparsed": unparsed}

    candidate_ids = filters.execute(job_id, fs) if fs else None
    ranked = ranker.rank(job_id, rubric_row["id"], candidate_ids)
    if fs:
        ranked = filters.apply_rank_filters(ranked, fs)

    candidates = [
        {**base_by_id[r["candidate_id"]], "overall": r["overall"], "scores": r["scores"]}
        for r in ranked
        if r["candidate_id"] in base_by_id
    ]
    return {"rubric_version": rubric_row["version"], "candidates": candidates, "unparsed": unparsed}


@router.get("/{job_id}/leaderboard")
async def get_leaderboard(job_id: int):
    """The master performance view for a job: every candidate, their score in each
    configured round (or null if that round hasn't produced one for them yet), an
    overall average across rounds with a score, a plain-English pipeline status, and a
    funnel count of how many candidates have cleared each round — everything the
    candidate table + funnel chart on the job page need in one call.
    """
    _get_job_or_404(job_id)
    with get_db() as conn:
        round_defs = conn.execute(
            "SELECT * FROM job_rounds WHERE job_id = ? ORDER BY order_index ASC", (job_id,)
        ).fetchall()
        cand_rows = conn.execute(
            "SELECT * FROM candidates WHERE job_id = ? ORDER BY id ASC", (job_id,)
        ).fetchall()
        result_rows = conn.execute(
            """SELECT rr.* FROM round_results rr
               JOIN candidates c ON c.id = rr.candidate_id WHERE c.job_id = ?""",
            (job_id,),
        ).fetchall()
        active_session_rows = conn.execute(
            "SELECT DISTINCT candidate_id FROM screening_sessions WHERE job_id = ? AND status = 'active'",
            (job_id,),
        ).fetchall()

    rounds = [{"round_key": r["round_key"], "name": r["name"]} for r in round_defs]
    scores_by_candidate: dict[int, dict[str, int | None]] = {}
    for row in result_rows:
        scores_by_candidate.setdefault(row["candidate_id"], {})[row["round"]] = row["score"]
    has_active_session = {row["candidate_id"] for row in active_session_rows}

    leaderboard = []
    funnel_counts = {r["round_key"]: 0 for r in rounds}

    for cand in cand_rows:
        cand_scores = scores_by_candidate.get(cand["id"], {})
        round_scores = []
        completed_count = 0
        first_incomplete_key = None
        for r in rounds:
            score = cand_scores.get(r["round_key"])
            round_scores.append({"round_key": r["round_key"], "score": score})
            if score is not None:
                completed_count += 1
                funnel_counts[r["round_key"]] += 1
            elif first_incomplete_key is None:
                first_incomplete_key = r["round_key"]

        numeric_scores = [s["score"] for s in round_scores if s["score"] is not None]
        overall = round(sum(numeric_scores) / len(numeric_scores), 1) if numeric_scores else None

        # Only "hr_screening" has an active trigger/session mechanism today, so an active
        # session only counts as "pending" when it's specifically the next round due —
        # otherwise (e.g. a stray/expired session for a different round) don't misattribute it.
        if rounds and completed_count == len(rounds):
            status = "All rounds completed"
        elif first_incomplete_key == "hr_screening" and cand["id"] in has_active_session:
            status = f"R{completed_count + 1} pending"
        elif completed_count > 0:
            status = f"R{completed_count} completed"
        else:
            status = "Not started"

        leaderboard.append(
            {
                "id": cand["id"],
                "job_id": job_id,
                "name": cand["name"],
                "email": cand["email"],
                "external_id": cand["external_id"],
                "source_type": cand["source_type"],
                "source_name": cand["source_name"],
                "application_date": cand["application_date"],
                "round_scores": round_scores,
                "overall": overall,
                "status": status,
            }
        )

    funnel = [
        {"round_key": r["round_key"], "name": r["name"], "count": funnel_counts[r["round_key"]]} for r in rounds
    ]

    return {
        "rounds": rounds,
        "candidates": leaderboard,
        "funnel": funnel,
        "total_candidates": len(cand_rows),
    }


def _get_candidate_or_404(job_id: int, candidate_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM candidates WHERE id = ? AND job_id = ?", (candidate_id, job_id)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found for job {job_id}")
    return dict(row)


@router.get("/{job_id}/candidates/{candidate_id}")
async def get_candidate_detail(job_id: int, candidate_id: int):
    """Full candidate detail for the candidate page: profile + one card per configured
    pipeline round (whatever's in job_rounds for this job, in order). Rounds with no
    result yet come back with result=null — the frontend renders those as empty/
    placeholder cards rather than omitting them.
    """
    _get_job_or_404(job_id)
    with get_db() as conn:
        cand_row = conn.execute(
            "SELECT * FROM candidates WHERE id = ? AND job_id = ?", (candidate_id, job_id)
        ).fetchone()
        if not cand_row:
            raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found")

        round_defs = conn.execute(
            "SELECT * FROM job_rounds WHERE job_id = ? ORDER BY order_index ASC", (job_id,)
        ).fetchall()
        round_rows = conn.execute(
            "SELECT * FROM round_results WHERE candidate_id = ?", (candidate_id,)
        ).fetchall()
        session_rows = conn.execute(
            """SELECT id, token, status, phase, created_at, expires_at, completed_at, summary, key_highlights
               FROM screening_sessions WHERE job_id = ? AND candidate_id = ? ORDER BY id DESC""",
            (job_id, candidate_id),
        ).fetchall()

    results_by_round = {}
    for row in round_rows:
        results_by_round[row["round"]] = {
            "score": row["score"],
            "summary": row["summary"],
            "key_highlights": json.loads(row["key_highlights_json"]) if row["key_highlights_json"] else [],
            "flags": json.loads(row["flags_json"]) if row["flags_json"] else [],
            "updated_at": row["updated_at"],
        }

    rounds = [
        {
            "round_key": r["round_key"],
            "name": r["name"],
            "description": r["description"],
            "is_builtin": bool(r["is_builtin"]),
            "is_ai_based": bool(r["is_ai_based"]),
            "result": results_by_round.get(r["round_key"]),
        }
        for r in round_defs
    ]

    sessions = []
    for row in session_rows:
        session = dict(row)
        if session["key_highlights"]:
            session["key_highlights"] = json.loads(session["key_highlights"])
        sessions.append(session)

    candidate = dict(cand_row)
    candidate["profile"] = json.loads(candidate.pop("profile_json"))
    screening_result_json = candidate.pop("screening_result_json")
    candidate["screening_result"] = json.loads(screening_result_json) if screening_result_json else None
    candidate["rounds"] = rounds
    candidate["screening_sessions"] = sessions
    return candidate


@router.post("/{job_id}/candidates/{candidate_id}/reject")
async def reject_candidate(job_id: int, candidate_id: int):
    """Mark a candidate rejected. Reversible (see /unreject) — the candidate stays in the
    pool and in candidate listings, just flagged, rather than being deleted or hidden."""
    _get_candidate_or_404(job_id, candidate_id)
    with get_db() as conn:
        conn.execute(
            "UPDATE candidates SET screening_decision = 'rejected' WHERE id = ? AND job_id = ?",
            (candidate_id, job_id),
        )
        conn.commit()
    return {"candidate_id": candidate_id, "screening_decision": "rejected"}


@router.post("/{job_id}/candidates/{candidate_id}/unreject")
async def unreject_candidate(job_id: int, candidate_id: int):
    """Undo a rejection."""
    _get_candidate_or_404(job_id, candidate_id)
    with get_db() as conn:
        conn.execute(
            "UPDATE candidates SET screening_decision = NULL WHERE id = ? AND job_id = ?",
            (candidate_id, job_id),
        )
        conn.commit()
    return {"candidate_id": candidate_id, "screening_decision": None}


@router.post("/{job_id}/candidates/{candidate_id}/screening-link", response_model=TriggerScreeningResponse)
async def trigger_screening(job_id: int, candidate_id: int, body: TriggerScreeningRequest | None = None):
    """HR action: create a tokenized, time-limited screening chat link for a candidate.

    `body.question_ids` is the recruiter's confirmed selection from the trigger modal
    (defaults + AI-recommended + any custom questions) — the chat asks exactly these,
    in order, before moving to profile-based follow-ups. Omitting it (or an empty list)
    falls back to every mandatory question on the job.

    Blocked for candidates the resume-screening pipeline rejected at the
    mandatory gate — see `engine.ScreeningGateError`.
    """
    question_ids = body.question_ids if body else []
    try:
        session = engine.create_session(job_id, candidate_id, selected_question_ids=question_ids)
    except engine.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except engine.ScreeningGateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()
    chat_url = f"{settings.frontend_base_url}/chat/{session['token']}"
    return TriggerScreeningResponse(token=session["token"], chat_url=chat_url, expires_at=session["expires_at"])


@router.get("/{job_id}/candidates/{candidate_id}/screening-sessions")
async def list_screening_sessions(job_id: int, candidate_id: int):
    """HR view: every screening session run for this candidate, with summary once completed."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, token, status, phase, created_at, expires_at, completed_at, summary, key_highlights
               FROM screening_sessions WHERE job_id = ? AND candidate_id = ? ORDER BY id DESC""",
            (job_id, candidate_id),
        ).fetchall()

    sessions = []
    for row in rows:
        session = dict(row)
        if session["key_highlights"]:
            session["key_highlights"] = json.loads(session["key_highlights"])
        sessions.append(session)
    return sessions


@router.get("/{job_id}/candidates/{candidate_id}/screening-sessions/{session_id}/answers")
async def get_screening_session_answers(job_id: int, candidate_id: int, session_id: int):
    """The exact question/answer pairs captured for one screening session — this is the
    recruiter-facing proof/evidence trail (question asked, exact candidate answer), as
    opposed to the full chat transcript which also includes small talk/acknowledgments."""
    with get_db() as conn:
        session_row = conn.execute(
            "SELECT id FROM screening_sessions WHERE id = ? AND job_id = ? AND candidate_id = ?",
            (session_id, job_id, candidate_id),
        ).fetchone()
        if not session_row:
            raise HTTPException(status_code=404, detail="Screening session not found")
        rows = conn.execute(
            """SELECT question_text, question_type, answer_text, created_at
               FROM screening_answers WHERE session_id = ? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# AI interview round (recruiter side)
# ---------------------------------------------------------------------------


@router.post("/{job_id}/candidates/{candidate_id}/interview-link", response_model=TriggerInterviewResponse)
async def trigger_interview(job_id: int, candidate_id: int, body: TriggerInterviewRequest):
    """Create a tokenized invite link for a candidate to schedule + take an AI interview
    round. Same copy-paste-the-link model as the HR screening link — nothing is sent
    anywhere. `body.round_key` selects which AI-based round on the job this is for.

    Blocked for candidates the resume-screening pipeline rejected at the mandatory gate.
    """
    try:
        session = interview_engine.create_session(job_id, candidate_id, body.round_key)
    except interview_engine.SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except interview_engine.InterviewStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except interview_engine.InterviewGateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()
    interview_url = f"{settings.frontend_base_url}/interview/{session['token']}"
    return TriggerInterviewResponse(
        token=session["token"], interview_url=interview_url, expires_at=session["expires_at"]
    )


@router.get("/{job_id}/candidates/{candidate_id}/interview-sessions")
async def list_interview_sessions(job_id: int, candidate_id: int, round_key: str | None = Query(default=None)):
    """Every AI interview session for this candidate (optionally filtered to one round),
    with score/summary once completed — what the recruiter round page + candidate page show."""
    query = (
        """SELECT id, token, round_key, status, phase, duration_minutes, scheduled_at, created_at,
                  expires_at, started_at, completed_at, recording_path, summary, score
           FROM interview_sessions WHERE job_id = ? AND candidate_id = ?"""
    )
    params: list = [job_id, candidate_id]
    if round_key:
        query += " AND round_key = ?"
        params.append(round_key)
    query += " ORDER BY id DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


@router.get("/{job_id}/candidates/{candidate_id}/interview-sessions/{session_id}")
async def get_interview_session_detail(job_id: int, candidate_id: int, session_id: int):
    """Full detail of one interview session: transcript, scorecard, proctoring events,
    and whether a recording is on file."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE id = ? AND job_id = ? AND candidate_id = ?",
            (session_id, job_id, candidate_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Interview session not found")
    session = dict(row)
    transcript = interview_engine.get_transcript(session_id)
    events = interview_engine.get_events(session_id)
    scorecard = json.loads(session["scorecard_json"]) if session["scorecard_json"] else None
    plan = json.loads(session["plan_json"]) if session["plan_json"] else None
    return {
        "id": session["id"],
        "round_key": session["round_key"],
        "status": session["status"],
        "phase": session["phase"],
        "duration_minutes": session["duration_minutes"],
        "scheduled_at": session["scheduled_at"],
        "created_at": session["created_at"],
        "started_at": session["started_at"],
        "completed_at": session["completed_at"],
        "score": session["score"],
        "summary": session["summary"],
        "scorecard": scorecard,
        "plan": plan,
        "has_recording": bool(session["recording_path"]),
        "transcript": transcript,
        "events": events,
    }


@router.get("/{job_id}/candidates/{candidate_id}/interview-sessions/{session_id}/recording")
async def get_interview_recording(job_id: int, candidate_id: int, session_id: int):
    """Stream the stored interview recording (if the round had recording enabled)."""
    from fastapi.responses import FileResponse

    with get_db() as conn:
        row = conn.execute(
            "SELECT recording_path FROM interview_sessions WHERE id = ? AND job_id = ? AND candidate_id = ?",
            (session_id, job_id, candidate_id),
        ).fetchone()
    if not row or not row["recording_path"]:
        raise HTTPException(status_code=404, detail="No recording on file for this interview")
    path = storage.candidates_dir(job_id) / row["recording_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Recording file is missing")
    return FileResponse(path, media_type="video/webm", filename=row["recording_path"])
