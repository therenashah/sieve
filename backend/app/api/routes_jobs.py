"""Jobs, JD/tracker/CV uploads, candidates. Everything here is recruiter-only."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from app import storage, tracker
from app.auth import require_auth
from app.config import get_settings
from app.conversations import engine
from app.db import get_db
from app.models import TriggerScreeningResponse
from app.pipeline import parser, rubric

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


@router.get("/{job_id}/candidates")
async def list_candidates(job_id: int):
    _get_job_or_404(job_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE job_id = ? ORDER BY match_score DESC, id ASC", (job_id,)
        ).fetchall()

    candidates = []
    for row in rows:
        candidate = dict(row)
        candidate["profile"] = json.loads(candidate.pop("profile_json"))
        screening_result_json = candidate.pop("screening_result_json")
        candidate["screening_result"] = json.loads(screening_result_json) if screening_result_json else None
        candidates.append(candidate)
    return candidates


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
