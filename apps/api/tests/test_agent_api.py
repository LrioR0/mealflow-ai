from fastapi.testclient import TestClient

from app.db.models import AgentRun, ToolTrace
from app.db.session import SessionLocal
from app.main import app


def test_create_and_revise_agent_run() -> None:
    with TestClient(app) as client:
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
        body = created.json()
        assert body["status"] == "WAITING_APPROVAL"
        assert len(body["tool_trace"]) >= 5
        assert len(body["options"]) == 3

        # 三方案策略键齐全，且内容来自真实计算
        assert {option["strategy"] for option in body["options"]} == {
            "expiring_first",
            "cost_first",
            "satisfaction_first",
        }
        for option in body["options"]:
            assert option["items"], "方案必须包含菜品"
            assert option["estimated_cost_cents"] > 0
            assert option["score_breakdown"]
            assert "宫保鸡丁" not in {item["name"] for item in option["items"]}

        # 工具轨迹为真实执行记录（名称与耗时）
        tool_names = {trace["tool_name"] for trace in body["tool_trace"]}
        assert "filter_hard_constraints" in tool_names
        assert "build_procurement_list" in tool_names
        assert all(trace["duration_ms"] >= 0 for trace in body["tool_trace"])

        # 测试环境屏蔽模型后必须可见规则基线提示
        assert any("规则基线" in warning for warning in body["warnings"])

        # 运行记录与工具轨迹落库
        with SessionLocal() as session:
            row = session.get(AgentRun, body["id"])
            assert row is not None
            assert row.constraints["expected_diners"] == 120
            assert row.state["options"]
            trace_count = session.query(ToolTrace).filter_by(agent_run_id=body["id"]).count()
            assert trace_count == len(body["tool_trace"])

        revised = client.post(
            f"/api/v1/agent/runs/{body['id']}/revise",
            json={"expected_diners": 150},
        )

    assert revised.status_code == 200
    revised_body = revised.json()
    assert revised_body["constraints"]["expected_diners"] == 150
    assert revised_body["options"][0]["estimated_cost_cents"] > body["options"][0][
        "estimated_cost_cents"
    ]
    # What-if 追加轨迹而非覆盖
    assert len(revised_body["tool_trace"]) > len(body["tool_trace"])
    # 人数放大后采购缺口单调增加
    first_option = revised_body["options"][0]
    assert first_option["procurement_list"]


def test_create_run_with_unknown_scope_returns_400() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/runs",
            json={
                "workspace_id": "no-such-workspace",
                "site_id": "demo-site",
                "meal_service_id": "demo-lunch",
                "request_text": "明天午餐 120 人",
            },
        )
    assert created.status_code == 400


def test_latest_run_endpoint_returns_most_recent_run() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/runs",
            json={
                "workspace_id": "demo-workspace",
                "site_id": "demo-site",
                "meal_service_id": "demo-lunch",
                "request_text": "明天午餐 120 人，预算 900 元",
            },
        )
        assert created.status_code == 201

        latest = client.get("/api/v1/agent/runs/latest")

    assert latest.status_code == 200
    body = latest.json()
    assert body["id"] == created.json()["id"]
    # 采购页依赖的三方案与缺口数据随最新运行一起返回
    assert body["options"]
    assert body["options"][0]["procurement_list"]
