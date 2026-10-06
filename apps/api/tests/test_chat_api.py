import json
from datetime import date

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.chat_service import (
    _DishTagFilter,
    _constraint_warnings_for_text,
    _dish_name_from_text,
    _fallback_general_text,
    _fallback_route,
    _filter_constraints,
    _format_warning_block,
)
from app.services.context_loader import InventoryLine, MemberConstraint, PlanningContext


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


def _status_items(events: list[tuple[str, dict]]) -> list[dict]:
    return [data for name, data in events if name == "status"]


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
    assert "thinking" not in names  # 未配置云端模型时无思维链事件

    # 步骤直播:首事件必须是"准备会话"running,每条 status 都带动态步骤名
    assert events[0][0] == "status"
    assert events[0][1]["step"] == "session"
    assert events[0][1]["state"] == "running"
    status_items = _status_items(events)
    assert all(item.get("label") for item in status_items)
    assert any("本地菜谱库" in item["label"] for item in status_items)
    assert any(
        item["step"] == "parse_request" and item["state"] == "done"
        for item in status_items
    )

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
    assert "plan" not in names
    # 闲聊也直播步骤:准备会话 → 理解需求 → 组织回答
    assert events[0][0] == "status"
    assert events[0][1]["step"] == "session"
    assert any(item["step"] == "compose_reply" for item in _status_items(events))
    assert all(item.get("label") for item in _status_items(events))
    assert _single(events, "done")["route"] == "general"


async def test_kitchen_qa_does_not_emit_planning_events() -> None:
    client = await _client()
    async with client:
        events = await _stream(client, "番茄怎么保存")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "thinking" not in names
    assert "plan" not in names
    # 问答也直播步骤:准备会话 → 理解需求 → 检查用餐限制 → 组织回答
    assert events[0][0] == "status"
    assert events[0][1]["step"] == "session"
    assert any(item["step"] == "compose_reply" for item in _status_items(events))
    assert any(
        item["step"] == "get_member_constraints" and item["state"] == "done"
        for item in _status_items(events)
    )
    # 顺序:检查用餐限制必须排在组织回答之前
    step_keys = [(item["step"], item["state"]) for item in _status_items(events)]
    assert step_keys.index(("get_member_constraints", "done")) < step_keys.index(
        ("compose_reply", "running")
    )
    assert _single(events, "done")["route"] == "kitchen_qa"


async def test_unknown_recipe_uses_recipe_route_without_plan() -> None:
    client = await _client()
    async with client:
        events = await _stream(client, "我想吃鲤鱼焙面")

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert "text" in names
    assert "plan" not in names
    # 本地菜谱库查询步骤必须出现(未命中也要如实说明)
    assert any(
        "本地菜谱库" in item.get("label", "") for item in _status_items(events)
    )
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
    assert "status" in names  # 问答对话同样直播步骤
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
    assert "text" in names
    assert "thinking" in names  # 规则分支也给出真实执行步骤的思考过程
    # 步骤直播:查过冰箱、查过本地库且命中数写实
    assert any("冰箱" in item["label"] for item in _status_items(events))
    assert any(
        item["step"] == "search_recipe_candidates"
        and item["state"] == "done"
        and "命中" in item["detail"]
        for item in _status_items(events)
    )
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
    # 本地库命中要在步骤里点名
    assert any(
        item["state"] == "done" and "虾仁炒蛋" in item["detail"]
        for item in _status_items(events)
    )
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
    assert "text" in names
    assert "thinking" in names  # 库存菜单的思考过程(读取冰箱/排序依据)
    # 步骤直播:调取冰箱 → 按现有食材匹配 → 核对忌口,全链路可见
    status_items = _status_items(events)
    assert any("冰箱" in item["label"] for item in status_items)
    assert any(
        item["step"] == "search_recipe_candidates"
        and item["state"] == "done"
        and item["detail"]
        for item in status_items
    )
    assert any(item["step"] == "filter_hard_constraints" for item in status_items)

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
    assert "status" in names  # 对话处理同样直播步骤
    assert "text" in names
    assert _single(events, "done")["route"] == "kitchen_qa"


def _planning_context_with(constraints: list[MemberConstraint]) -> PlanningContext:
    return PlanningContext(
        workspace_id="w1",
        workspace_name="我家",
        site_name="家庭厨房",
        meal_service_id="ms1",
        meal_service_name="午餐",
        service_date=date(2026, 10, 7),
        expected_diners=2,
        budget_limit_cents=None,
        inventory=[
            InventoryLine(key="tofu", name="豆腐", quantity=1, unit="盒", expires_on=None)
        ],
        recipes=[],
        members=[],
        member_constraints=constraints,
        excluded_keys=[],
    )


def _demo_constraints() -> list[MemberConstraint]:
    return [
        MemberConstraint(
            user_id="u-lrio",
            member_name="Lrio",
            kind="restriction",
            level="warn",
            summary="Lrio·忌口tofu",
            ingredient_key="tofu",
        ),
        MemberConstraint(
            user_id="u-colin",
            member_name="Colin",
            kind="event",
            level="warn",
            summary="Colin·上火(忌辛辣、忌油炸)",
            avoid_tags=["辛辣", "油炸"],
        ),
    ]


def test_filter_constraints_by_selected_diners() -> None:
    """勾选了用餐成员时只保留他们的约束;未勾选/空列表视为全员。"""
    lrio, colin = _demo_constraints()
    assert _filter_constraints([lrio, colin], ["u-lrio"]) == [lrio]
    assert _filter_constraints([lrio, colin], None) == [lrio, colin]
    assert _filter_constraints([lrio, colin], []) == [lrio, colin]


def test_constraint_warnings_for_text() -> None:
    """回答文本涉及忌口食材 → 必须生成引用成员的提示;推荐类回答必带事件口味提醒。"""
    context = _planning_context_with(_demo_constraints())

    warnings = _constraint_warnings_for_text("玉米豆腐羹：嫩豆腐切小块，加玉米粒煮2分钟", context, True)
    assert any("Lrio·忌口tofu" in w and "豆腐" in w for w in warnings)
    assert any("Colin·上火" in w for w in warnings)

    # 与忌口食材无关、且非菜品推荐的回答 → 不产生提示
    assert _constraint_warnings_for_text("番茄怎么保存", context, False) == []

    block = _format_warning_block(warnings)
    assert block.startswith("\n\n**忌口与状态提示**")
    assert "Lrio" in block
    assert _format_warning_block([]) == ""


def test_dish_keyword_cleaning_for_external_search() -> None:
    """下厨房等外部搜索只留干净关键词:时间状语/意图动词/语气词一律剥掉。"""
    assert _dish_name_from_text("明天想吃黄焖鸡") == "黄焖鸡"
    assert _dish_name_from_text("今晚来一份可乐鸡翅吧") == "可乐鸡翅"
    assert _dish_name_from_text("鲅鱼饺子怎么做") == "鲅鱼饺子"

    dish_filter = _DishTagFilter()
    dish_filter.feed("推荐如下:\n<dishes>明天想吃黄焖鸡|番茄炒蛋</dishes>\n")
    assert dish_filter.dishes == ["黄焖鸡", "番茄炒蛋"]


async def test_fridge_ingredient_followup_routes_to_inventory() -> None:
    """「根据冰箱现有食材吧」这类省略句式必须进库存菜单分支,不能落到问答说没权限。"""
    client = await _client()
    async with client:
        events = await _stream(client, "根据冰箱现有食材吧")

    names = [name for name, _ in events]
    assert "candidates" in names
    assert any("冰箱" in item["label"] for item in _status_items(events))
    assert _single(events, "done")["route"] == "kitchen_recipe"
