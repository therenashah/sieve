from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # LLM provider: AWS Bedrock (via the hackathon EC2 instance's IAM role,
    # or static AWS_* creds if running elsewhere)
    aws_region: str = "ap-south-1"
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    # RAG (lexical term-frequency retrieval — no embedding API/provider needed)
    knowledge_base_dir: str = "../data/knowledge_base"
    rag_top_k: int = 3

    # storage
    database_path: str = "./db/app.db"
    jobs_storage_dir: str = "../data/jobs"

    # recruiter auth (single-tenant, demo-grade — no user table)
    recruiter_email: str = "recruiter@seclore.com"
    recruiter_password: str = "seclore123"
    recruiter_session_ttl_hours: int = 12

    # candidate auth
    screening_link_ttl_minutes: int = 15
    frontend_base_url: str = "http://localhost:3000"

    # screening conversation bounds (keeps the chat from being open-ended)
    max_profile_followups: int = 2
    max_seclore_qa_turns: int = 5
    max_context_messages: int = 16

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
