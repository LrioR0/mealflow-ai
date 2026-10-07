"""LangGraph 状态图与旧顺序编排的行为对拍:同输入必须产出一致结果。"""

from httpx import AsyncClient, ASGITransport

from app.agent.graph import build_meal_planning_graph
from app.main import app
from app.services import agent_service


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_graph_matches_legacy_orchestration() -> None:
    """graph.invoke 与旧 _plan 顺序编排:菜单项/成本/工具轨迹完全一致。"""
    client = await _client()
    async with client:
        # 经 API 跑一次图驱动的 create_run(会落库),再直接读回
        response = await client.post(
            "/api/v1/agent/runs",
            json={
                "workspace_id": "home-workspace",
                "site_id": "home-kitchen",
                "meal_service_id": "home-lunch",
                "request_text": "我们俩吃一顿，预算 60 元",
            },
        )
    assert response.status_code == 201
    graph_run = response.json()

    # 同输入直接调旧编排(不落库)对拍:选 expiring_first 策略对比
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.models import MealService, Site
    from app.db.session import SessionLocal
    from app.llm.factory import build_llm_provider
    from app.services.context_loader import load_planning_context

    with SessionLocal() as session:
        site_id = session.scalar(select(Site.id).limit(1))
        meal_service_id = session.scalar(
            select(MealService.id).where(MealService.site_id == site_id).limit(1)
        )
        context = load_planning_context(session, "home-workspace", site_id, meal_service_id)
    provider = build_llm_provider(get_settings())
    constraints, _trace, _used = await agent_service._parse_constraints_with_llm(
        provider, "我们俩吃一顿，预算 60 元", context
    )
    traces, options, _warnings, _chips = agent_service._plan(
        context, constraints, agent_service.ToolTraceView(
            tool_name="parse_request", status="success", duration_ms=0,
            input_summary="对拍", output_summary="对拍",
        )
    )
    legacy = next(o for o in options if o.strategy == "expiring_first")
    graphed = next(
        o
        for o in graph_run["options"]
        if o["strategy"] == "expiring_first"
    )
    assert [i["name"] for i in graphed["items"]] == [i["name"] for i in legacy.items]
    assert graphed["estimated_cost_cents"] == legacy.estimated_cost_cents
    assert len(graph_run["tool_trace"]) == len(traces)


def test_graph_compiles_and_runs_nodes() -> None:
    graph = build_meal_planning_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"parse_request", "load_context", "build_options", "wait_for_human"} <= nodes
