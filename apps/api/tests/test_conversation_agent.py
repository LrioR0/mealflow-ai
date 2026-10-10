from datetime import date

import pytest

from app.agent.conversation import run_conversation_agent, stream_conversation_agent
from app.services.context_loader import InventoryLine, PlanningContext, RecipeContext, RecipeIngredientLine


def _context() -> PlanningContext:
    recipe = RecipeContext(
        id="r-1",
        name="番茄炒蛋",
        servings=2,
        duration_minutes=12,
        kcal_per_serving=180,
        estimated_cost_cents=800,
        tags=["快手"],
        taste_tags=["家常"],
        allergens=[],
        ingredients=[
            RecipeIngredientLine(key="tomato", name="番茄", quantity=2, unit="个", optional=False),
            RecipeIngredientLine(key="starch", name="淀粉", quantity=1, unit="勺", optional=False),
        ],
    )
    return PlanningContext(
        workspace_id="workspace",
        workspace_name="家",
        site_name="厨房",
        meal_service_id="lunch",
        meal_service_name="午餐",
        service_date=date(2026, 10, 8),
        expected_diners=2,
        budget_limit_cents=None,
        inventory=[InventoryLine(key="tomato", name="番茄", quantity=2, unit="个", expires_on=None)],
        recipes=[recipe],
        members=[],
        member_constraints=[],
        excluded_keys=[],
    )


class _ScriptedProvider:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[list[dict]] = []

    async def chat_with_tools(self, *, messages, tools):
        self.calls.append(messages)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_agent_executes_readonly_tool_then_uses_result(monkeypatch) -> None:
    provider = _ScriptedProvider(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "get_inventory_summary", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "冰箱里有番茄，可以做番茄炒蛋。"},
        ]
    )
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())

    turn = await run_conversation_agent(
        provider=provider,
        workspace_id="workspace",
        site_id="kitchen",
        meal_service_id="lunch",
        diner_ids=None,
        user_text="冰箱有什么？",
        history=[],
        max_steps=4,
    )

    assert turn is not None
    assert "番茄" in turn.text
    assert [trace.tool_name for trace in turn.traces] == ["get_inventory_summary"]
    assert turn.traces[0].status == "success"
    assert any(message["role"] == "tool" for message in provider.calls[1])


@pytest.mark.asyncio
async def test_agent_caps_tool_loop(monkeypatch) -> None:
    inventory_response = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "get_inventory_summary", "arguments": "{}"},
            }
        ],
    }
    preference_response = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "get_preference_summary", "arguments": "{}"},
            }
        ],
    }
    provider = _ScriptedProvider([inventory_response, preference_response])
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())

    turn = await run_conversation_agent(
        provider=provider,
        workspace_id="workspace",
        site_id="kitchen",
        meal_service_id="lunch",
        diner_ids=None,
        user_text="看看库存",
        history=[],
        max_steps=2,
    )

    assert turn is not None
    assert len(turn.traces) == 2
    assert len(provider.calls) == 2
    assert "避免重复查询" in turn.text


@pytest.mark.asyncio
async def test_stream_emits_running_before_tool_done(monkeypatch) -> None:
    provider = _ScriptedProvider([
        {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "get_inventory_summary", "arguments": "{}"}}]},
        {"role": "assistant", "content": "已查到库存。"},
    ])
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())
    events = [event async for event in stream_conversation_agent(provider=provider, workspace_id="workspace", site_id="kitchen", meal_service_id="lunch", diner_ids=None, user_text="看看库存", history=[], max_steps=4)]
    tool_events = [event for event in events if event["type"] == "tool"]
    assert [event["trace"].status for event in tool_events] == ["running", "success"]
    assert events.index(tool_events[0]) < events.index(tool_events[1])


@pytest.mark.asyncio
async def test_pantry_staple_is_not_procurement_suggestion(monkeypatch) -> None:
    provider = _ScriptedProvider([
        {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "check_recipe_availability", "arguments": '{"recipe":"番茄炒蛋"}'}}]},
        {"role": "assistant", "content": "可以做。"},
    ])
    context = _context(); context.pantry_keys = {"starch"}
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: context)
    turn = await run_conversation_agent(provider=provider, workspace_id="workspace", site_id="kitchen", meal_service_id="lunch", diner_ids=None, user_text="番茄炒蛋能做吗", history=[], max_steps=4)
    assert turn is not None
    assert turn.procurement_suggestions == []
    assert turn.traces[0].status == "success"


@pytest.mark.asyncio
async def test_duplicate_tool_calls_reuse_result_without_spending_budget(monkeypatch) -> None:
    call = {"id": "call", "type": "function", "function": {"name": "search_recipes", "arguments": '{"query":"番茄"}'}}
    provider = _ScriptedProvider([
        {"role": "assistant", "tool_calls": [call, {**call, "id": "call-2"}, {**call, "id": "call-3"}]},
        {"role": "assistant", "content": "番茄炒蛋可以做。"},
    ])
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())
    turn = await run_conversation_agent(provider=provider, workspace_id="workspace", site_id="kitchen", meal_service_id="lunch", diner_ids=None, user_text="查番茄菜", history=[], max_steps=6)
    assert turn is not None
    assert len(turn.traces) == 3
    assert sum(trace.duration_ms > 0 for trace in turn.traces) == 1
    assert sum("已复用本轮结果" in trace.output_summary for trace in turn.traces) == 2


@pytest.mark.asyncio
async def test_procurement_suggestions_are_deduplicated_across_recipe_tools(monkeypatch) -> None:
    provider = _ScriptedProvider([
        {"role": "assistant", "tool_calls": [{"id": "detail", "type": "function", "function": {"name": "get_recipe_detail", "arguments": '{"recipe":"番茄炒蛋"}'}}]},
        {"role": "assistant", "tool_calls": [{"id": "availability", "type": "function", "function": {"name": "check_recipe_availability", "arguments": '{"recipe":"番茄炒蛋"}'}}]},
        {"role": "assistant", "content": "已整理好。"},
    ])
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())

    turn = await run_conversation_agent(
        provider=provider,
        workspace_id="workspace",
        site_id="kitchen",
        meal_service_id="lunch",
        diner_ids=None,
        user_text="番茄炒蛋缺什么",
        history=[],
        max_steps=6,
    )

    assert turn is not None
    assert [item["ingredient"] for item in turn.procurement_suggestions] == ["淀粉"]


@pytest.mark.asyncio
async def test_recommend_menu_returns_structured_menu(monkeypatch) -> None:
    provider = _ScriptedProvider([
        {"role": "assistant", "tool_calls": [{"id": "menu", "type": "function", "function": {"name": "recommend_menu", "arguments": '{"dish_count":2,"staple":"米饭"}'}}]},
        {"role": "assistant", "content": "已为你整理菜单。"},
    ])
    monkeypatch.setattr("app.agent.conversation._load_context", lambda *args: _context())
    turn = await run_conversation_agent(provider=provider, workspace_id="workspace", site_id="kitchen", meal_service_id="lunch", diner_ids=None, user_text="两人两道菜配米饭", history=[], max_steps=6)
    assert turn is not None
    assert turn.menu_recommendation is not None
    assert turn.menu_recommendation["staple"] == "米饭"
    assert turn.menu_recommendation["items"][0]["name"] == "番茄炒蛋"
