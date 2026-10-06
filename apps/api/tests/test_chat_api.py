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
    """样例A:点名辣子鸡+2人+预算60块 → 规划分支下线后走单菜做法分支(无 plan/步骤/追问)。"""
    client = await _client()
    async with client:
        events = await _stream(client, "明天中午想吃辣子鸡,我们俩,预算 60 块")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "plan" not in names
    assert "questions" not in names
    assert "status" not in names
    assert "thinking" not in names  # 未配置云端模型时无思维链事件

    done = _single(events, "done")
    assert done["session_id"]
    assert done["route"] == "kitchen_recipe"

    text = next(data for name, data in events if name == "text")["delta"]
    assert "辣子鸡" in text


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


async def test_golden_sample_c_vague_request_goes_qa() -> None:
    """样例C:规划分支下线后,模糊吃饭诉求按厨房问答对话处理,不再追问人数/预算。"""
    client = await _client()
    async with client:
        events = await _stream(client, "晚上吃点清淡的")

    names = [name for name, _ in events]
    assert "plan" not in names
    assert "questions" not in names
    assert "status" not in names
    assert "text" in names
    assert _single(events, "done")["route"] == "kitchen_qa"


async def test_fuzzy_ingredient_search_returns_candidates() -> None:
    """模糊查询:今晚想吃虾 → candidates 候选列表带过敏标注,无 run/步骤事件。"""
    client = await _client()
    async with client:
        events = await _stream(client, "今晚想吃虾")

    names = [name for name, _ in events]
    assert "candidates" in names
    assert "plan" not in names
    assert "status" not in names
    assert "text" in names
    assert "thinking" in names  # 规则分支也给出真实执行步骤的思考过程
    done = _single(events, "done")
    assert done["route"] == "kitchen_recipe"
    assert done["provider"] is None  # 列表是规则召回,不依赖模型

    candidates = _single(events, "candidates")
    assert candidates["query"] == "虾"
    item_names = {item["name"] for item in candidates["items"]}
    assert "虾仁炒蛋" in item_names
    assert "白灼虾" in item_names
    conflict = next(item for item in candidates["items"] if item["name"] == "白灼虾")
    assert conflict["conflict_level"] == "forbidden"  # 对象虾过敏 → 红线标注

    # 菜单列表统一带库存标注:虾仁炒蛋用冰箱的鸡蛋,虾仁不在库存如实标缺
    egg_item = next(item for item in candidates["items"] if item["name"] == "虾仁炒蛋")
    assert "鸡蛋" in egg_item["used_fridge"]
    assert "虾仁" in egg_item["missing"]

    text = next(data for name, data in events if name == "text")["delta"]
    assert "虾" in text


async def test_fuzzy_dish_name_takes_priority_over_ingredient() -> None:
    """菜名精确命中优先:我想吃虾仁炒蛋 直接给做法,不发候选列表。"""
    client = await _client()
    async with client:
        events = await _stream(client, "我想吃虾仁炒蛋")

    names = [name for name, _ in events]
    assert "candidates" not in names
    assert "text" in names
    assert _single(events, "done")["route"] == "kitchen_recipe"
    text = next(data for name, data in events if name == "text")["delta"]
    assert "虾仁炒蛋" in text


async def test_inventory_menu_ranks_expiring_first() -> None:
    """库存菜单:Agent 自读冰箱出候选,临期优先排序,标注用到的库存食材与缺口。"""
    client = await _client()
    async with client:
        events = await _stream(client, "根据冰箱库存去生成一些菜单供我选，优先使用临期的")

    names = [name for name, _ in events]
    assert "candidates" in names
    assert "plan" not in names
    assert "status" not in names
    assert "text" in names
    assert "thinking" in names  # 库存菜单的思考过程(读取冰箱/排序依据)

    candidates = _single(events, "candidates")
    assert candidates["query"] == "冰箱库存"
    first = candidates["items"][0]
    assert first["expiring"] is True, "用到临期食材的菜必须排最前"
    assert first["used_fridge"], "必须标注使用了冰箱的哪些食材"

    text = next(data for name, data in events if name == "text")["delta"]
    assert "临期" in text
    assert _single(events, "done")["route"] == "kitchen_recipe"


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


async def test_confirm_message_after_plan_removal() -> None:
    """规划分支下线后,确认类消息按对话处理,不再触发方案确认/采购链路。"""
    client = await _client()
    async with client:
        events = await _stream(client, "就做这套,确认")

    names = [name for name, _ in events]
    assert "plan" not in names
    assert "status" not in names
    assert "text" in names
    assert _single(events, "done")["route"] == "kitchen_qa"
