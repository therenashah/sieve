from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # LLM providers
    anthropic_api_key: str = ""  # unused now that client.py calls Claude via Bedrock; kept for local-dev fallback
    openai_api_key: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "anthropic.claude-haiku-4-5-20251001-v1:0"  # Bedrock model ID

    # AWS Bedrock — auth resolves via boto3's default credential chain
    # (EC2 instance role on the deployment box; no access key needed there)
    aws_region: str = "us-east-1"

    # storage
    database_path: str = "./db/sieve.db"

    # candidate auth
    screening_link_ttl_minutes: int = 15

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
