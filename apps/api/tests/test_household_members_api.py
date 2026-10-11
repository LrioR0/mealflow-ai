from fastapi.testclient import TestClient

from app.main import app


def test_member_optional_text_can_be_cleared() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/household/members",
            json={
                "workspace_id": "home-workspace",
                "display_name": "清空字段测试成员",
                "gender": "保密",
                "residency": "guest",
                "taboo": "不吃香菜",
                "note": "测试备注",
            },
        )
        assert created.status_code == 201
        member = next(
            item
            for item in created.json()["members"]
            if item["display_name"] == "清空字段测试成员"
        )

        cleared = client.patch(
            f"/api/v1/household/members/{member['user_id']}",
            json={"taboo": None, "note": None},
        )
        assert cleared.status_code == 200
        updated = next(
            item
            for item in cleared.json()["members"]
            if item["user_id"] == member["user_id"]
        )
        assert updated["taboo"] is None
        assert updated["note"] is None

        deleted = client.delete(f"/api/v1/household/members/{member['user_id']}")
        assert deleted.status_code == 204


def test_food_preference_can_be_created_updated_listed_and_deleted() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/household/preferences",
            json={
                "workspace_id": "home-workspace",
                "user_id": "home-me",
                "target_type": "dish",
                "target_key": "cold-cucumber",
                "target_name": "任意测试凉菜",
                "preference": "dislike",
                "source": "conversation",
            },
        )
        assert created.status_code == 201
        owner = next(item for item in created.json()["members"] if item["user_id"] == "home-me")
        assert len(owner["food_preferences"]) == 1
        preference = owner["food_preferences"][0]
        assert preference["target_name"] == "任意测试凉菜"
        assert preference["preference"] == "dislike"

        updated = client.post(
            "/api/v1/household/preferences",
            json={
                "workspace_id": "home-workspace",
                "user_id": "home-me",
                "target_type": "dish",
                "target_key": "cold-cucumber",
                "target_name": "任意测试凉菜",
                "preference": "like",
                "source": "profile",
            },
        )
        assert updated.status_code == 201
        owner = next(item for item in updated.json()["members"] if item["user_id"] == "home-me")
        assert len(owner["food_preferences"]) == 1
        assert owner["food_preferences"][0]["preference"] == "like"

        deleted = client.delete(f"/api/v1/household/preferences/{preference['id']}")
        assert deleted.status_code == 204
        household = client.get("/api/v1/household").json()
        owner = next(item for item in household["members"] if item["user_id"] == "home-me")
        assert owner["food_preferences"] == []
