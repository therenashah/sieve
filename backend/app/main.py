import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_auth, routes_chat, routes_jobs
from app.auth import require_auth
from app.config import get_settings
from app.db import get_db, init_db
from app.models import HealthResponse

logger = logging.getLogger("sieve")

settings = get_settings()

app = FastAPI(title="Sieve — Recruitment Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_auth.router)
app.include_router(routes_jobs.router)
app.include_router(routes_chat.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()

    # Index any new knowledge base docs (pure lexical indexing, no external API — safe on every startup).
    try:
        from app.rag.ingest import ingest_knowledge_base

        indexed = ingest_knowledge_base()
        if indexed:
            logger.info("Indexed %d knowledge base chunk(s) on startup", indexed)
    except Exception:
        logger.warning("Knowledge base auto-index skipped", exc_info=True)

    # Backfill round_results for candidates the resume-screening pipeline already scored
    # before that bridge existed (or if it's ever silently missed one) — DB-only, cheap,
    # idempotent, safe on every startup.
    try:
        from app.pipeline.scorer import backfill_resume_screening_round_results

        backfilled = backfill_resume_screening_round_results()
        if backfilled:
            logger.info("Backfilled resume-screening round_results for %d candidate(s)", backfilled)
    except Exception:
        logger.warning("Resume-screening round_results backfill skipped", exc_info=True)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(app_env=settings.app_env)


@app.get("/api/search", dependencies=[Depends(require_auth)])
async def search(q: str = ""):
    """Minimal global search for the navbar — job titles and candidate names, both by
    simple substring match. Good enough to jump straight to a posting or candidate;
    not a ranked/fuzzy search."""
    q = q.strip()
    if not q:
        return {"jobs": [], "candidates": []}

    like = f"%{q}%"
    with get_db() as conn:
        jobs = conn.execute(
            "SELECT id, title FROM jobs WHERE title LIKE ? ORDER BY id DESC LIMIT 5", (like,)
        ).fetchall()
        candidates = conn.execute(
            "SELECT id, job_id, name, external_id FROM candidates WHERE name LIKE ? ORDER BY id DESC LIMIT 5",
            (like,),
        ).fetchall()

    return {"jobs": [dict(r) for r in jobs], "candidates": [dict(r) for r in candidates]}
