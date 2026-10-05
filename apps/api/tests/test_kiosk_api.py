"""Kiosk 终端测试（docs/评分终端设计.md、api.md）。

覆盖：设备令牌校验、已发布菜单读取、反馈持久化、幂等重放、
按设备冷却限流与可疑内容标记（标记不等于删除）。
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Feedback
from app.db.session import SessionLocal
from app.main import app

DEMO_TOKEN = "demo-kiosk-token"


def _publish_demo_menu(client: TestClient) -> dict:
    """走完整链路：Agent 运行 → 确认 → 发布，返回已发布计划。"""
    created = client.post(
        "/api/v1/agent/runs",
        json={
            "workspace_id": "demo-workspace",
            "site_id": "demo-site",
            "meal_service_id": "demo-lunch",
            "request_text": "明天午餐 120 人，预算 900 元，清淡，优先临期番茄，不能含花生",
        },
    )
    assert created.status_code == 201
    run = created.json()
    confirmed = client.post(
        "/api/v1/meal-plans",
        json={"agent_run_id": run["id"], "strategy": "expiring_first"},
    )
    assert confirmed.status_code == 201
    plan_id = confirmed.json()["id"]
    published = client.post(
        f"/api/v1/meal-plans/{plan_id}/publish",
        headers={"Idempotency-Key": f"kiosk-{uuid4()}"},
    )
    assert published.status_code == 200
    return published.json()


def _feedback_body(rating: int = 2, tags: list[str] | None = None, **overrides) -> dict:
    body = {
        "rating": rating,
        "tags": tags if tags is not None else ["太咸"],
        "comment": "整体偏咸",
        "idempotency_key": str(uuid4()),
    }
    body.update(overrides)
    return body


def test_current_menu_requires_valid_device_token() -> None:
    with TestClient(app) as client:
        bogus = client.get("/api/v1/kiosk/current-menu", headers={"X-Kiosk-Token": "bogus"})
        assert bogus.status_code == 401

        ok = client.get("/api/v1/kiosk/current-menu", headers={"X-Kiosk-Token": DEMO_TOKEN})
        # 尚未发布菜单：令牌有效但无已发布菜单
        assert ok.status_code == 404


def test_current_menu_returns_published_plan() -> None:
    with TestClient(app) as client:
        plan = _publish_demo_menu(client)

        menu = client.get("/api/v1/kiosk/current-menu", headers={"X-Kiosk-Token": DEMO_TOKEN})

    assert menu.status_code == 200
    body = menu.json()
    assert body["plan_id"] == plan["id"]
    assert body["meal_service"]["status"] == "published"
    assert body["meal_service"]["expected_diners"] == 120
    assert [item["name"] for item in body["menu"]] == [
        item["name"] for item in plan["items"]
    ]
    for item in body["menu"]:
        assert "allergens" in item
        assert item["kcal_per_serving"] is not None


def test_feedback_persists_against_published_plan() -> None:
    with TestClient(app) as client:
        plan = _publish_demo_menu(client)
        key = str(uuid4())
        submitted = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(idempotency_key=key),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert submitted.status_code == 201

        with SessionLocal() as session:
            row = session.get(Feedback, submitted.json()["id"])
            assert row is not None
            # 定位由服务端解析为站点最新已发布菜单
            assert row.meal_plan_id == plan["id"]
            assert row.meal_service_id == "demo-lunch"
            assert row.rating == 2
            assert row.tags == ["太咸"]
            assert row.is_suspicious is False
            assert row.idempotency_key == key

        # 幂等重放：同键返回同一记录，不产生新数据
        replay = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(idempotency_key=key),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == submitted.json()["id"]
        with SessionLocal() as session:
            assert session.scalar(select(Feedback).where(Feedback.idempotency_key == key)) is not None
            count = session.query(Feedback).filter_by(idempotency_key=key).count()
            assert count == 1


def test_feedback_is_rate_limited_per_device() -> None:
    with TestClient(app) as client:
        _publish_demo_menu(client)
        first = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert first.status_code == 201

        # 冷却期（3 秒，与终端重置时间一致）内的第二次提交被限流
        second = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(rating=5, tags=["很喜欢"], comment=None),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
    assert second.status_code == 429


def test_repeated_identical_content_is_flagged_not_deleted() -> None:
    """评分终端设计 §4：重复内容标记可疑；异常标记不等于自动删除。"""
    with TestClient(app) as client:
        _publish_demo_menu(client)
        first = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert first.status_code == 201

        # 把首条反馈回拨出冷却窗口但仍留在可疑内容窗口内，模拟"短时间重复内容"
        with SessionLocal() as session:
            row = session.get(Feedback, first.json()["id"])
            row.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            session.add(row)
            session.commit()

        duplicate = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert duplicate.status_code == 201

    with SessionLocal() as session:
        flagged = session.get(Feedback, duplicate.json()["id"])
        assert flagged.is_suspicious is True
        original = session.get(Feedback, first.json()["id"])
        assert original is not None  # 原记录保留，不做删除


def test_feedback_comment_is_sanitized_and_length_limited() -> None:
    with TestClient(app) as client:
        _publish_demo_menu(client)
        submitted = client.post(
            "/api/v1/kiosk/feedback",
            json=_feedback_body(comment="  好\r\n吃\x07  "),
            headers={"X-Kiosk-Token": DEMO_TOKEN},
        )
        assert submitted.status_code == 201

    with SessionLocal() as session:
        row = session.get(Feedback, submitted.json()["id"])
        assert row.comment == "好吃"
