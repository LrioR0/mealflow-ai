from fastapi.testclient import TestClient

from app.main import app


def test_default_pantry_returns_chinese_labels() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/household/pantry/home-workspace")

    assert response.status_code == 200
    body = response.json()
    labels = {item["key"]: item["label"] for item in body["effective_items"]}
    assert labels["cooking_wine"] == "料酒"
    assert labels["dark_soy_sauce"] == "老抽"
    assert labels["oil"] == "食用油"
    assert all(item["is_custom"] is False for item in body["effective_items"])


def test_custom_pantry_survives_default_toggle_and_can_be_removed() -> None:
    with TestClient(app) as client:
        original = client.get("/api/v1/household/pantry/home-workspace").json()
        try:
            disabled = client.put(
                "/api/v1/household/pantry/home-workspace",
                json={
                    "use_defaults": False,
                    "disabled_default_keys": [],
                    "custom_keys": ["测试黄油"],
                },
            )
            assert disabled.status_code == 200
            body = disabled.json()
            assert body["effective_keys"] == ["测试黄油"]
            assert body["effective_items"] == [
                {"key": "测试黄油", "label": "测试黄油", "is_custom": True}
            ]

            removed = client.put(
                "/api/v1/household/pantry/home-workspace",
                json={
                    "use_defaults": False,
                    "disabled_default_keys": [],
                    "custom_keys": [],
                },
            )
            assert removed.status_code == 200
            assert removed.json()["effective_items"] == []
        finally:
            client.put(
                "/api/v1/household/pantry/home-workspace",
                json={
                    "use_defaults": original["use_defaults"],
                    "disabled_default_keys": original["disabled_default_keys"],
                    "custom_keys": original["custom_keys"],
                },
            )
