from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://localhost:5432/heirloom"

    # Signs the admin panel's session cookie. Required: set a long random value per environment.
    secret_key: str
    # Send the admin cookie over HTTPS only. Turn on everywhere except local development.
    secure_cookies: bool = False

    # Where uploaded audio is kept (local disk for now; S3 at deploy time).
    storage_dir: Path = Path("storage")
    max_audio_mb: int = 25  # Groq's upload limit

    # Comma-separated in the environment.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "https://heirloom-staging.storywriter.net",
        "https://heirloom.storywriter.net",
    ]

    # Groq. Model names come only from the environment: Groq retires models without notice.
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str | None = None
    groq_scoring_model: str | None = None
    # Sent as reasoning_effort for reasoning models (gpt-oss: low/medium/high). Unset: not sent.
    groq_scoring_reasoning_effort: str | None = None
    groq_transcription_model: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
