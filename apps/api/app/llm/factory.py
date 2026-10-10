from app.core.config import Settings
from app.llm.model_catalog import resolve_model_profile
from app.llm.openai_compatible import OpenAICompatibleCloudProvider
from app.llm.provider import LLMProvider


def build_llm_provider(settings: Settings, model_id: str | None = None) -> LLMProvider | None:
    profile = resolve_model_profile(settings, model_id)
    if profile is None:
        return None
    return OpenAICompatibleCloudProvider(
        api_key=profile.api_key,
        api_style=profile.api_style,
        base_url=profile.base_url,
        model=profile.model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
