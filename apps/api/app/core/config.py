from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 仓库根目录（apps/api/app/core/config.py -> 上五级，与 seed.py 的 parents[4] 一致）。
# 数据库等相对路径统一锚定到这里，避免从 apps/api 或 IDE 启动时
# 解析成 apps/api/data/local 下的另一份副本，导致两人看到不同数据。
REPO_ROOT = Path(__file__).resolve().parents[4]


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
    llm_api_style: str = "chat_completions"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 30
    aitechflux_api_key: str = ""
    aitechflux_base_url: str = "https://aitechflux.com/v1"
    aitechflux_gpt_model: str = "gpt-6.1-sol"
    aitechflux_grok_model: str = "grok-4.7"
    #智普模型
    bigmodel_api_key: str = ""
    bigmodel_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    bigmodel_model: str = "glm-4.7-flash"
    # 仅用于对话 Agent 的只读工具循环；正式配餐图不受该值影响。
    agent_max_steps: int = 6
    kiosk_token_secret: str = "replace-in-real-environment"

    @field_validator("database_url", mode="after")
    @classmethod
    def anchor_sqlite_path(cls, value: str) -> str:
        """把 sqlite:///./xxx 形式的相对路径锚定到仓库根目录，保证只有一个共享库。"""
        prefix = "sqlite:///./"
        if value.startswith(prefix):
            return f"sqlite:///{(REPO_ROOT / value.removeprefix(prefix)).as_posix()}"
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("agent_max_steps", mode="after")
    @classmethod
    def clamp_agent_max_steps(cls, value: int) -> int:
        """工具循环保持有限，防止意外配置导致无限查询或不可控成本。"""
        return max(1, min(value, 8))


@lru_cache
def get_settings() -> Settings:
    return Settings()
