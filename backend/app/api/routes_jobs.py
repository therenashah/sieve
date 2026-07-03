"""Jobs, JD/tracker/CV uploads, candidates. Everything here is recruiter-only."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app import storage, tracker
from app.auth import require_auth
from app.config import get_settings
from app.conversations import engine
from app.db import get_db
from app.models import Criterion, FilterParseRequest, FilterSet, Rubric, RubricChatRequest, TriggerScreeningResponse
from app.pipeline import filters, parser, ranker, rubric, scorer

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
        conn.commit()
        job_id = cur.lastrowid

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


def _get_candidate_or_404(job_id: int, candidate_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM candidates WHERE id = ? AND job_id = ?", (candidate_id, job_id)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found for job {job_id}")
    return dict(row)


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
async def trigger_screening(job_id: int, candidate_id: int):
    """HR action: create a tokenized, time-limited screening chat link for a candidate.

    Blocked for candidates the resume-screening pipeline rejected at the
    mandatory gate — see `engine.ScreeningGateError`.
    """
    try:
        session = engine.create_session(job_id, candidate_id)
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
