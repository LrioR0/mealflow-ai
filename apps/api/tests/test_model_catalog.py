from app.core.config import Settings
from app.llm.factory import build_llm_provider
from app.llm.model_catalog import list_model_profiles, resolve_model_profile


def _settings() -> Settings:
    return Settings(
        llm_provider="deepseek",
        llm_api_style="chat_completions",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="deepseek-test-key",
        llm_model="deepseek-v4-pro",
        bigmodel_api_key="bigmodel-test-key",
        bigmodel_base_url="https://open.bigmodel.cn/api/paas/v4/",
        bigmodel_text_model="glm-4.5-air",
        bigmodel_vision_model="glm-4.6v",
        aitechflux_api_key="aitechflux-test-key",
    )


def test_catalog_exposes_default_and_aitechflux_models_without_keys() -> None:
    profiles = list_model_profiles(_settings())
    assert [profile.id for profile in profiles] == [
        "bigmodel-glm-4.5-air",
        "bigmodel-glm-4.6v",
        "deepseek-v4-pro",
        "aitechflux-gpt-6.1-sol",
        "aitechflux-grok-4.7",
    ]
    assert profiles[0].is_default is True
    assert all(profile.enabled for profile in profiles)
    assert all("api_key" not in profile.public_view() for profile in profiles)


def test_missing_aitechflux_key_disables_optional_models() -> None:
    settings = _settings()
    settings.aitechflux_api_key = ""
    profiles = list_model_profiles(settings)
    by_id = {profile.id: profile for profile in profiles}
    assert by_id["bigmodel-glm-4.5-air"].enabled is True
    assert by_id["bigmodel-glm-4.6v"].enabled is True
    assert by_id["bigmodel-glm-4.5-air"].is_free is False
    assert by_id["deepseek-v4-pro"].enabled is True
    assert by_id["aitechflux-gpt-6.1-sol"].enabled is False
    assert by_id["aitechflux-grok-4.7"].enabled is False
    assert resolve_model_profile(settings, "aitechflux-gpt-6.1-sol") is None


def test_factory_routes_each_model_without_changing_default(monkeypatch) -> None:
    captured = []

    def fake_provider(**kwargs):
        captured.append(kwargs)
        return object()

    monkeypatch.setattr("app.llm.factory.OpenAICompatibleCloudProvider", fake_provider)
    settings = _settings()
    model_ids = (
        None,
        "bigmodel-glm-4.5-air",
        "bigmodel-glm-4.6v",
        "aitechflux-gpt-6.1-sol",
        "aitechflux-grok-4.7",
    )
    for model_id in model_ids:
        assert build_llm_provider(settings, model_id) is not None
    assert [item["model"] for item in captured] == [
        "glm-4.5-air",
        "glm-4.5-air",
        "glm-4.6v",
        "gpt-6.1-sol",
        "grok-4.7",
    ]
    assert captured[0]["api_key"] == captured[1]["api_key"] == "bigmodel-test-key"
    assert captured[1]["api_key"] == captured[2]["api_key"] == "bigmodel-test-key"
    assert captured[3]["api_key"] == captured[4]["api_key"] == "aitechflux-test-key"
    assert captured[3]["base_url"] == "https://aitechflux.com/v1"


def test_unknown_model_does_not_fall_back_to_paid_default() -> None:
    assert build_llm_provider(_settings(), "unknown-model") is None
