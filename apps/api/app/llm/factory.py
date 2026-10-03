from app.core.config import Settings
from app.llm.openai_compatible import OpenAICompatibleCloudProvider
from app.llm.provider import LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider | None:
    if not (settings.llm_api_key and settings.llm_base_url and settings.llm_model):
        return None
    return OpenAICompatibleCloudProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
