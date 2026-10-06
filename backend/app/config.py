"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "AI Meeting Assistant"
    app_base_url: str = "http://localhost:8000"
    secret_key: str = "replace-me"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://meeting:meeting@localhost:5432/meeting_assistant"
    redis_url: str = "redis://localhost:6379/0"

    auth_mode: Literal["dev", "supabase"] = "dev"
    access_token_ttl_seconds: int = 60 * 60 * 12
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_storage_bucket: str = "meeting-audio"

    audio_retention_days: int = Field(default=30, ge=1, le=3650)
    transcript_retention_days: int = Field(default=365, ge=1, le=3650)

    storage_backend: Literal["local", "supabase"] = "local"
    local_storage_dir: str = "./data/audio"
    max_upload_bytes: int = Field(default=262_144_000, ge=1)
    max_meeting_duration_seconds: int = Field(default=10_800, ge=1)
    signed_url_ttl_seconds: int = Field(default=900, ge=60, le=86_400)

    max_meetings_per_user: int = Field(default=50, ge=1, le=10_000)
    max_questions_per_day: int = Field(default=100, ge=1, le=10_000)
    max_audio_minutes_per_user_per_month: int = Field(default=30, ge=1, le=100_000)
    max_llm_tokens_per_user_per_month: int = Field(default=500_000, ge=1, le=100_000_000)
    redact_pii: bool = True
    seed_demo_on_startup: bool = False
    demo_user_email: str = "demo@example.com"
    max_uploads_per_ip_per_day: int = Field(default=20, ge=0, le=100_000)

    job_runner: Literal["inline", "rq"] = "inline"
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    audio_preprocess_mode: Literal["auto", "mock", "ffmpeg"] = "auto"
    openai_api_key: str = ""
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_diarization_model: str = "gpt-4o-transcribe-diarize"
    openai_summary_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_qa_model: str = "gpt-4o-mini"
    transcription_max_file_bytes: int = Field(default=25_000_000, ge=1)

    sentry_dsn: str = ""
    app_version: str = "0.1.0"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "local", "dev", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
