"""反馈聚合回流测试（评分终端设计 §5、Agent 设计 §6）。

反馈只影响满意度等软评分，不突破过敏原等硬约束；低样本向中性值收缩；
下一次规划的工具轨迹与方案理由中可见反馈驱动的可解释变化。
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Feedback, KioskDevice, MealService, Site
from app.db.session import SessionLocal
from app.main import app
from app.services.context_loader import DishFeedbackStats
from app.services.planning import feedback_component

DEMO_TOKEN = "demo-kiosk-token"


def test_feedback_component_maps_rating_and_shrinks_low_samples() -> None:
    assert feedback_component(None) == 0.5
    assert feedback_component(DishFeedbackStats(avg_rating=3.0, sample_count=0)) == 0.5
    # 样本充足：1 分 → 0，5 分 → 1
    assert feedback_component(DishFeedbackStats(avg_rating=1.0, sample_count=5)) == 0.0
    assert feedback_component(DishFeedbackStats(avg_rating=5.0, sample_count=5)) == 1.0
    # 低样本：向中性值 0.5 收缩（1 分 1 条 → 0.5 + (0 - 0.5) * 0.2 = 0.4）
    assert feedback_component(DishFeedbackStats(avg_rating=1.0, sample_count=1)) == 0.4


def _publish_menu(client: TestClient) -> dict:
    created = client.post(
        "/api/v1/agent/runs",
        json={
            "workspace_id": "demo-workspace",
            "site_id": "demo-site",
            "meal_service_id": "demo-lunch",
            "request_text": "明天午餐 120 人，预算 900 元，清淡，优先临期番茄，不能含花生",
        },
    )
    run = created.json()
    confirmed = client.post(
        "/api/v1/meal-plans",
        json={"agent_run_id": run["id"], "strategy": "expiring_first"},
    )
    plan_id = confirmed.json()["id"]
    published = client.post(
        f"/api/v1/meal-plans/{plan_id}/publish",
        headers={"Idempotency-Key": f"loop-{uuid4()}"},
    )
    return published.json()


def _submit(client: TestClient, rating: int, tags: list[str], comment: str) -> None:
    submitted = client.post(
        "/api/v1/kiosk/feedback",
        json={"rating": rating, "tags": tags, "comment": comment, "idempotency_key": str(uuid4())},
        headers={"X-Kiosk-Token": DEMO_TOKEN},
    )
    assert submitted.status_code == 201


def _submit_two_diners(client: TestClient) -> None:
    """模拟两位用餐者先后反馈：绕过 3 秒冷却但不触发重复内容标记。"""
    _submit(client, 2, ["太咸", "太辣"], "太咸了")
    with SessionLocal() as session:
        row = session.scalars(select(Feedback)).first()
        row.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        session.add(row)
        session.commit()
    _submit(client, 1, ["太咸"], "咸到无法接受")


def test_feedback_summary_aggregates_by_meal_and_dish() -> None:
    with TestClient(app) as client:
        _publish_menu(client)
        _submit_two_diners(client)

        summary = client.get(
            "/api/v1/feedback/summary",
            params={"workspace_id": "demo-workspace", "meal_service_id": "demo-lunch"},
        )

    assert summary.status_code == 200
    body = summary.json()
    assert body["sample_count"] == 2
    assert body["suspicious_count"] == 0
    assert body["avg_rating"] == 1.5
    assert body["top_tags"][0] == "太咸"
    assert body["tag_counts"] == {"太咸": 2, "太辣": 1}
    assert body["dishes"], "聚合必须细化到菜品"
    for dish in body["dishes"]:
        assert dish["sample_count"] == 2
        assert dish["avg_rating"] == 1.5
        assert dish["top_tags"][0] == "太咸"
    assert len(body["comment_digest"]) == 2


def test_next_planning_consumes_feedback_summary() -> None:
    with TestClient(app) as client:
        _publish_menu(client)
        _submit_two_diners(client)

        next_run = client.post(
            "/api/v1/agent/runs",
            json={
                "workspace_id": "demo-workspace",
                "site_id": "demo-site",
                "meal_service_id": "demo-lunch",
                "request_text": "明天午餐 120 人，预算 900 元，优先临期番茄，不能含花生",
            },
        )
        assert next_run.status_code == 201
        body = next_run.json()

    feedback_trace = next(
        trace for trace in body["tool_trace"] if trace["tool_name"] == "get_feedback_summary"
    )
    assert "2 条反馈" in feedback_trace["output_summary"]
    assert "菜品聚合" in feedback_trace["output_summary"]

    for option in body["options"]:
        assert option["score_breakdown"]["feedback"] != 0.5, "有反馈数据时不应再取中性值"
    reasons_text = "；".join(
        reason for option in body["options"] for reason in option["reasons"]
    )
    assert "反馈回流" in reasons_text, "方案理由必须解释反馈驱动的调整"
    assert "太咸" in reasons_text


def test_feedback_summary_scoped_by_workspace() -> None:
    with TestClient(app) as client:
        summary = client.get(
            "/api/v1/feedback/summary",
            params={"workspace_id": "other-workspace", "meal_service_id": "demo-lunch"},
        )
    assert summary.status_code == 404


def test_daily_feedback_groups_menu_and_entries() -> None:
    """运营概览：≤10 条全部展示，含当天菜单。"""
    with TestClient(app) as client:
        published = _publish_menu(client)
        _submit_two_diners(client)

        daily = client.get("/api/v1/feedback/daily", params={"workspace_id": "demo-workspace"})

    assert daily.status_code == 200
    days = daily.json()
    assert days, "至少返回一天"
    day = days[0]
    assert day["meal_service_name"] == "午餐"
    assert [item["name"] for item in published["items"]] == day["dishes"]
    assert day["feedback_count"] == 2
    assert day["summary"] is None
    assert day["entries"] is not None
    assert [entry["rating"] for entry in day["entries"]] == [2, 1]
    assert day["entries"][0]["tags"] == ["太咸", "太辣"]


def test_daily_feedback_summarizes_when_more_than_ten() -> None:
    """>10 条自动概括，不逐条展示。"""
    with TestClient(app) as client:
        published = _publish_menu(client)

        from datetime import datetime, timedelta, timezone as tz

        with SessionLocal() as session:
            plan_id = published["id"]
            device = session.scalars(select(KioskDevice)).first()
            for index in range(11):
                session.add(
                    Feedback(
                        device_id=device.id,
                        meal_service_id="demo-lunch",
                        meal_plan_id=plan_id,
                        rating=2,
                        tags=["太咸"],
                        comment=f"批量反馈 {index}",
                        is_suspicious=False,
                    )
                )
            session.commit()

        daily = client.get("/api/v1/feedback/daily", params={"workspace_id": "demo-workspace"})

    assert daily.status_code == 200
    day = daily.json()[0]
    assert day["feedback_count"] == 11
    assert day["entries"] is None
    summary = day["summary"]
    assert summary["sample_count"] == 11
    assert summary["avg_rating"] == 2.0
    assert summary["top_tags"] == ["太咸"]
    assert summary["comment_digest"]


def test_daily_feedback_unknown_workspace_404() -> None:
    with TestClient(app) as client:
        daily = client.get("/api/v1/feedback/daily", params={"workspace_id": "no-such"})
    assert daily.status_code == 404


def test_meal_service_site_scope_unchanged() -> None:
    """回归：反馈回流不破坏餐次-站点-工作区作用域校验。"""
    with SessionLocal() as session:
        meal_service = session.get(MealService, "demo-lunch")
        site = session.get(Site, meal_service.site_id)
        assert site.workspace_id == "demo-workspace"
