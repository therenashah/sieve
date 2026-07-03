from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_chat, routes_jobs
from app.config import get_settings
from app.db import init_db
from app.models import HealthResponse

settings = get_settings()

app = FastAPI(title="Sieve — Recruitment Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_jobs.router)
app.include_router(routes_chat.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(app_env=settings.app_env)
