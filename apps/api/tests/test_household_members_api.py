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
