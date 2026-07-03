from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"

    # LLM providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_provider: str = "anthropic"

    # storage
    database_path: str = "./db/app.db"

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
