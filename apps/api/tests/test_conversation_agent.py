from datetime import date

import pytest

from app.agent.conversation import run_conversation_agent
from app.services.context_loader import InventoryLine, PlanningContext, RecipeContext


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
    tool_response = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "get_inventory_summary", "arguments": "{}"},
            }
        ],
    }
    provider = _ScriptedProvider([tool_response, tool_response, tool_response])
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
