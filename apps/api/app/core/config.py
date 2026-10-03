from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "MealFlow API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/local/mealflow.sqlite3"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    demo_mode: bool = True

    llm_provider: str = "qwen"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 30
    agent_max_steps: int = 12
    kiosk_token_secret: str = "replace-in-real-environment"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
