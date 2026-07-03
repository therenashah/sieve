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

    # Model tiering for the AI interview round: a fast/cheap model for low-stakes
    # turns (clarifications, "can you repeat", intent classification) and a smarter
    # model for the expensive reasoning (interview plan generation, adaptive
    # next-question selection against profile+rubric, and final scoring). The fast
    # tier defaults to the same Haiku profile above; the smart tier is Sonnet.
    # If the smart profile isn't enabled in the account, the interview engine falls
    # back to the fast/default model rather than failing (see llm.client).
    bedrock_model_id_fast: str = ""  # empty -> falls back to bedrock_model_id
    bedrock_model_id_smart: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    # AWS Polly text-to-speech for the AI interviewer's voice.
    polly_voice_id: str = "Joanna"
    polly_engine: str = "neural"

    @property
    def fast_model_id(self) -> str:
        return self.bedrock_model_id_fast or self.bedrock_model_id

    @property
    def smart_model_id(self) -> str:
        return self.bedrock_model_id_smart or self.bedrock_model_id

    # RAG (lexical term-frequency retrieval — no embedding API/provider needed)
    knowledge_base_dir: str = "../data/knowledge_base"
    rag_top_k: int = 3

    # storage
    database_path: str = "./db/sieve.db"
    jobs_storage_dir: str = "../data/jobs"

    # recruiter auth (single-tenant, demo-grade — no user table)
    recruiter_email: str = "recruiter@seclore.com"
    recruiter_password: str = "seclore123"
    recruiter_session_ttl_hours: int = 12

    # candidate auth
    screening_link_ttl_minutes: int = 15
    frontend_base_url: str = "http://localhost:3000"

    # AI interview round
    interview_link_ttl_days: int = 7          # invite link validity + scheduling window
    interview_default_duration_minutes: int = 30
    interview_hard_stop_grace_minutes: int = 5   # forced end this far past the target
    interview_max_followups_per_question: int = 2
    interview_scheduling_slot_hours: str = "9,11,13,15,17"  # local hours offered per day

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
