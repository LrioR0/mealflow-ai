from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app


def test_list_inventory_returns_real_seed_data() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/workspaces/demo-workspace/inventory")

    assert response.status_code == 200
    items = response.json()
    names = {item["ingredient_key"]: item for item in items}
    assert "tomato" in names
    assert names["tomato"]["is_expiring"] is True
    assert names["rice"]["is_expiring"] is False


def test_add_update_delete_inventory_item() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "carrot", "quantity": 4.5, "expires_on": None},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["ingredient_name"] == "胡萝卜"
        assert body["unit"] == "kg"  # 未传单位时使用食材默认单位
        item_id = body["id"]

        # 同一食材再次新增 → upsert 更新而非重复
        again = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "carrot", "quantity": 6},
        )
        assert again.status_code == 201
        listed = client.get("/api/v1/workspaces/demo-workspace/inventory").json()
        carrot_items = [item for item in listed if item["ingredient_key"] == "carrot"]
        assert len(carrot_items) == 1
        assert carrot_items[0]["quantity"] == "6"

        patched = client.patch(
            f"/api/v1/inventory/{item_id}", json={"expires_on": str(date.today())}
        )
        assert patched.status_code == 200
        assert patched.json()["is_expiring"] is True

        deleted = client.delete(f"/api/v1/inventory/{item_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/inventory/{item_id}").status_code in (404, 405)


def test_inventory_validation_rules() -> None:
    with TestClient(app) as client:
        # 数据字典：数量不得小于 0
        negative = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "rice", "quantity": -1},
        )
        assert negative.status_code == 422

        # 单位不一致必须人工确认，不能静默合并
        mismatch = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "rice", "quantity": 1, "unit": "个"},
        )
        assert mismatch.status_code == 400
        assert "人工确认" in mismatch.json()["detail"]

        # 不存在的食材
        missing = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "unicorn", "quantity": 1},
        )
        assert missing.status_code == 400

        # 不存在的工作区
        missing_ws = client.get("/api/v1/workspaces/nope/inventory")
        assert missing_ws.status_code == 404


def test_expiring_window_is_two_days() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/workspaces/demo-workspace/inventory",
            json={"ingredient_key": "beef", "quantity": 2, "expires_on": str(date.today() + timedelta(days=2))},
        )
        assert created.json()["is_expiring"] is True
        client.delete(f"/api/v1/inventory/{created.json()['id']}")
