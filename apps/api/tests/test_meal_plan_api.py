"""菜单确认与发布链路测试（api.md：POST /meal-plans、POST /meal-plans/{id}/publish）。"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AgentRun, AgentRunStatus, MealPlan, MealService
from app.db.session import SessionLocal
from app.main import app


def _create_run(client: TestClient) -> dict:
    created = client.post(
        "/api/v1/agent/runs",
        json={
            "workspace_id": "home-workspace",
            "site_id": "home-kitchen",
            "meal_service_id": "home-lunch",
            "request_text": "明天午餐 120 人，预算 900 元，清淡，优先临期番茄，不能含花生",
        },
    )
    assert created.status_code == 201
    return created.json()


def _confirm(client: TestClient, run: dict, strategy: str = "expiring_first") -> object:
    return client.post(
        "/api/v1/meal-plans",
        json={"agent_run_id": run["id"], "strategy": strategy},
    )


def test_confirm_and_publish_full_chain() -> None:
    with TestClient(app) as client:
        run = _create_run(client)

        confirmed = _confirm(client, run)
        assert confirmed.status_code == 201
        plan = confirmed.json()
        assert plan["status"] == "draft"
        assert plan["strategy"] == "expiring_first"
        assert plan["agent_run_id"] == run["id"]
        assert plan["estimated_cost_cents"] > 0
        # 数据字典：菜单项含 recipe_id 与生成时的评分拆解快照
        assert plan["items"]
        assert all(item["recipe_id"] for item in plan["items"])
        assert all(item["score_breakdown"] for item in plan["items"])
        assert plan["constraints_snapshot"].get("expected_diners") == 120

        # 确认后运行记录进入已确认状态，但尚未发布
        with SessionLocal() as session:
            run_row = session.get(AgentRun, run["id"])
            assert run_row.state["approval_status"] == "approved"
            assert run_row.status == AgentRunStatus.WAITING_APPROVAL.value
            assert session.get(MealService, "home-lunch").status == "draft"

        # 重复确认同一方案返回同一计划（不产生重复数据）
        again = _confirm(client, run)
        assert again.status_code == 201
        assert again.json()["id"] == plan["id"]

        # 发布必须携带 Idempotency-Key
        missing_key = client.post(f"/api/v1/meal-plans/{plan['id']}/publish")
        assert missing_key.status_code == 400

        published = client.post(
            f"/api/v1/meal-plans/{plan['id']}/publish",
            headers={"Idempotency-Key": "demo-publish-1"},
        )
        assert published.status_code == 200
        published_body = published.json()
        assert published_body["status"] == "published"
        assert published_body["published_at"] is not None

        # 发布副作用：餐次 published、运行 PUBLISHED
        with SessionLocal() as session:
            assert session.get(MealService, "home-lunch").status == "published"
            assert session.get(AgentRun, run["id"]).status == AgentRunStatus.PUBLISHED.value

        # 同键重放返回同一结果；换键重发冲突
        replay = client.post(
            f"/api/v1/meal-plans/{plan['id']}/publish",
            headers={"Idempotency-Key": "demo-publish-1"},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == published_body["id"]

        conflict = client.post(
            f"/api/v1/meal-plans/{plan['id']}/publish",
            headers={"Idempotency-Key": "demo-publish-2"},
        )
        assert conflict.status_code == 409


def test_publish_requires_admin_confirmation() -> None:
    """未经确认的草稿不能发布（api.md：发布要求管理员确认状态）。"""
    with TestClient(app) as client:
        run = _create_run(client)
        confirmed = _confirm(client, run)
        plan_id = confirmed.json()["id"]

        # 绕过确认直接抹掉确认状态，模拟未确认草稿
        with SessionLocal() as session:
            run_row = session.get(AgentRun, run["id"])
            run_row.state = {**run_row.state, "approval_status": "waiting"}
            session.add(run_row)
            session.commit()

        denied = client.post(
            f"/api/v1/meal-plans/{plan_id}/publish",
            headers={"Idempotency-Key": "demo-publish-x"},
        )
    assert denied.status_code == 409


def test_confirm_with_unknown_run_or_strategy() -> None:
    with TestClient(app) as client:
        missing_run = client.post(
            "/api/v1/meal-plans",
            json={"agent_run_id": "no-such-run", "strategy": "expiring_first"},
        )
        assert missing_run.status_code == 404

        run = _create_run(client)
        bad_strategy = _confirm(client, run, strategy="cheap_first")
        assert bad_strategy.status_code == 400


def test_get_plan_endpoint_unknown_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/meal-plans/no-such-plan")
    assert response.status_code == 404


def test_saved_plan_rows_are_scoped_to_workspace() -> None:
    """数据字典：库存、菜单等业务数据统一按 workspace 归属。"""
    with TestClient(app) as client:
        run = _create_run(client)
        confirmed = _confirm(client, run)
        plan_id = confirmed.json()["id"]

    with SessionLocal() as session:
        plan = session.get(MealPlan, plan_id)
        assert plan.workspace_id == "home-workspace"
        assert plan.meal_service_id == "home-lunch"
        assert session.scalar(
            select(MealPlan).where(MealPlan.publish_idempotency_key == "unused-key")
        ) is None
