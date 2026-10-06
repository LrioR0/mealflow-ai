import json

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.chat_service import _fallback_general_text, _fallback_route


def _parse_sse_blocks(blocks: list[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in blocks:
        name = None
        data: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if name is not None:
            events.append((name, data))
    return events


async def _stream(client: AsyncClient, message: str) -> list[tuple[str, dict]]:
    blocks: list[str] = []
    buffer = ""
    async with client.stream(
        "POST",
        "/api/v1/agent/chat/stream",
        json={"message": message},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                blocks.append(block)
    return _parse_sse_blocks(blocks)


def _single(events: list[tuple[str, dict]], name: str) -> dict:
    for event_name, data in events:
        if event_name == name:
            return data
    raise AssertionError(f"缺少 {name} 事件")


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_golden_sample_a_named_dish_with_budget() -> None:
    """样例A:点名辣子鸡+2人+预算60块 → 全阶段事件、plan 必附菜单、预算进约束。"""
    client = await _client()
    async with client:
        events = await _stream(client, "明天中午想吃辣子鸡,我们俩,预算 60 块")

    names = [name for name, _ in events]
    assert names[0] == "status"
    assert names[-1] == "done"
    assert "text" in names and "plan" in names and "questions" in names
    assert "thinking" not in names  # 未配置云端模型时无思维链事件

    done = _single(events, "done")
    assert done["session_id"]

    plan = _single(events, "plan")
    options = plan["options"]
    assert options and options[0]["items"], "方案卡必须附菜单"
    menu_names = {item["name"] for item in options[0]["items"]}
    assert "辣子鸡" in menu_names, "点名菜必须进主推荐"
    assert options[0]["estimated_cost_cents"] > 0

    # 预算 60 块被识别为约束(6000 分)
    run_constraints = plan["constraints"]
    assert run_constraints["expected_diners"] == 2
    assert run_constraints["budget_limit_cents"] == 6000

    text = next(data for name, data in events if name == "text")["delta"]
    assert "辣子鸡" in text
    assert "市区大型超市" in text, "金额必须带价格来源标注"

    questions = _single(events, "questions")["items"]
    assert questions


def test_chat_route_separates_general_and_kitchen_topics() -> None:
    assert _fallback_route("你好") == "general"
    assert _fallback_route("今天天气怎么样") == "general"
    assert _fallback_route("番茄怎么保存") == "kitchen_qa"
    assert _fallback_route("土豆能做什么菜") == "kitchen_qa"
    assert _fallback_route("我想吃焖面条") == "kitchen_recipe"
    assert _fallback_route("我想吃鲤鱼焙面") == "kitchen_recipe"
    assert _fallback_route("想吃辣子鸡，给我个方案") == "kitchen_plan"
    assert _fallback_route("想吃辣子鸡，两个人，预算60元") == "kitchen_plan"
    assert _fallback_route("帮我看看冰箱里有什么") == "kitchen_plan"
    assert _fallback_route("安排两个人的晚餐") == "kitchen_plan"
    assert "实时天气" in _fallback_general_text("今天天气怎么样")


async def test_general_chat_does_not_emit_planning_events() -> None:
    client = await _client()
    async with client:
        events = await _stream(client, "你好")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "thinking" not in names
    assert "status" not in names
    assert "plan" not in names
    assert _single(events, "done")["route"] == "general"


async def test_kitchen_qa_does_not_emit_planning_events() -> None:
    client = await _client()
    async with client:
        events = await _stream(client, "番茄怎么保存")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "thinking" not in names
    assert "status" not in names
    assert "plan" not in names
    assert _single(events, "done")["route"] == "kitchen_qa"


async def test_unknown_recipe_uses_recipe_route_without_plan() -> None:
    client = await _client()
    async with client:
        events = await _stream(client, "我想吃鲤鱼焙面")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "status" not in names
    assert "plan" not in names
    done = _single(events, "done")
    assert done["route"] == "kitchen_recipe"
    assert done["search_query"] == "鲤鱼焙面"


async def test_golden_sample_c_clarify_when_missing_info() -> None:
    """样例C:信息不足时主动补问,不出方案。"""
    client = await _client()
    async with client:
        events = await _stream(client, "晚上吃点清淡的")

    names = [name for name, _ in events]
    assert "plan" not in names
    questions = _single(events, "questions")
    assert questions["needs_input"] is True
    assert questions["items"]

    text = _single(events, "text")["delta"]
    assert "几个人" in text


async def test_session_restore_after_chat() -> None:
    """会话可恢复:对话后 GET 会话,消息(含用户与助手)持久化。"""
    client = await _client()
    async with client:
        events = await _stream(client, "明天中午我俩想吃豆角焖面,预算 60 块")
        session_id = _single(events, "done")["session_id"]

        response = await client.get(f"/api/v1/agent/chat/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    roles = [message["role"] for message in body["messages"]]
    assert roles[0] == "user"
    assert "assistant" in roles


async def test_confirm_intent_publishes_plan() -> None:
    """确认链路:生成方案后说"就做这套",返回确认文本与采购信息。"""
    client = await _client()
    async with client:
        await _stream(client, "明天中午想吃辣子鸡,我们俩,预算 60 块")
        events = await _stream(client, "就做这套,确认")

    text = _single(events, "text")["delta"]
    assert "已确认" in text
    assert "采购清单" in text or "冰箱现有食材" in text
