"""Filesystem layout for per-job artifacts, backed by a mounted volume so it
survives container restarts:

    {jobs_storage_dir}/{job_id}/{job_id}_JD.<ext>
    {jobs_storage_dir}/{job_id}/candidates/{candidate_external_id}_CV.<ext>

CV matching reads the uploaded zip straight out of memory and only writes the
entries it can confidently match — no full extract-to-disk pass, which is
what keeps a 50-100 CV batch fast.
"""

import difflib
import io
import re
import shutil
import zipfile
from pathlib import Path

from app.config import get_settings

_RESUME_EXTS = {".pdf", ".doc", ".docx"}
_IGNORED_ENTRY_PREFIXES = ("__MACOSX/", ".")
_FUZZY_MATCH_THRESHOLD = 0.72


def _storage_root() -> Path:
    settings = get_settings()
    root = Path(settings.jobs_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_dir(job_id: int) -> Path:
    path = _storage_root() / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def candidates_dir(job_id: int) -> Path:
    path = job_dir(job_id) / "candidates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete_job_dir(job_id: int) -> None:
    """Remove everything on disk for a job (JD file, CVs, interview recordings) — the
    DB side of a job delete cascades via foreign keys, but files aren't part of that."""
    path = _storage_root() / str(job_id)
    shutil.rmtree(path, ignore_errors=True)


def save_jd_file(job_id: int, original_filename: str, content: bytes) -> tuple[str, Path]:
    ext = Path(original_filename).suffix.lower() or ".pdf"
    filename = f"{job_id}_JD{ext}"
    path = job_dir(job_id) / filename
    path.write_bytes(content)
    return filename, path


def normalize(text: str) -> str:
    """Lowercase, alphanumeric-only — makes 'Bobby Singh' and 'bobbysingh_final(1)' comparable."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _candidate_extension_prefix(candidate: dict) -> str:
    external_id = str(candidate.get("external_id") or candidate["id"])
    return f"{external_id}_CV"


def process_cv_zip(job_id: int, zip_bytes: bytes, candidates: list[dict]) -> dict:
    """Match each resume in the zip to a candidate by (normalized) filename vs.
    candidate name, write matched files to disk renamed to `{candidate_id}_CV.ext`,
    and report anything that couldn't be confidently matched.
    """
    dest_dir = candidates_dir(job_id)

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("That file isn't a valid .zip archive.") from exc

    file_infos = []
    for entry in zf.namelist():
        base = Path(entry).name
        if entry.endswith("/") or not base or base.startswith(_IGNORED_ENTRY_PREFIXES) or "__MACOSX" in entry:
            continue
        ext = Path(entry).suffix.lower()
        if ext not in _RESUME_EXTS:
            continue
        file_infos.append((entry, normalize(Path(entry).stem), ext))

    skipped_non_resume = [
        Path(e).name for e in zf.namelist() if not e.endswith("/") and Path(e).suffix.lower() not in _RESUME_EXTS
    ]

    candidates_by_norm: dict[str, dict] = {normalize(c["name"]): c for c in candidates if c.get("name")}
    unresolved = list(candidates)
    matched: list[tuple[str, str, dict]] = []
    remaining_files = []

    # Pass 1: exact normalized-name match (cheap, resolves the common case).
    for entry, norm, ext in file_infos:
        cand = candidates_by_norm.get(norm)
        if cand and cand in unresolved:
            matched.append((entry, ext, cand))
            unresolved.remove(cand)
        else:
            remaining_files.append((entry, norm, ext))

    # Pass 2: fuzzy match whatever's left (handles suffixes like "_resume_final", typos).
    for entry, norm, ext in remaining_files:
        best_candidate, best_score = None, 0.0
        for cand in unresolved:
            cand_norm = normalize(cand["name"])
            if not cand_norm:
                continue
            score = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
            if cand_norm in norm or norm in cand_norm:
                score = max(score, 0.9)
            if score > best_score:
                best_score, best_candidate = score, cand
        if best_candidate and best_score >= _FUZZY_MATCH_THRESHOLD:
            matched.append((entry, ext, best_candidate))
            unresolved.remove(best_candidate)

    matched_entries = {entry for entry, _, _ in matched}
    unmatched_files = [Path(e).name for e, _, _ in remaining_files if e not in matched_entries]

    results = []
    for entry, ext, cand in matched:
        dest_name = f"{_candidate_extension_prefix(cand)}{ext}"
        (dest_dir / dest_name).write_bytes(zf.read(entry))
        results.append(
            {
                "candidate_id": cand["id"],
                "external_id": cand.get("external_id"),
                "name": cand["name"],
                "file": dest_name,
                "source_filename": Path(entry).name,
            }
        )

    return {
        "matched": results,
        "unmatched_files": unmatched_files,
        "unmatched_candidates": [
            {"id": c["id"], "external_id": c.get("external_id"), "name": c["name"]} for c in unresolved
        ],
        "skipped_non_resume_files": skipped_non_resume,
        "total_files_in_zip": len(file_infos),
        "total_candidates": len(candidates),
    }
