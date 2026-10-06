"""对话编排服务:意图路由、约束前置、点名菜冲突检测、流式事件生成。

事件协议(docs/V2改造方案 §8.1):thinking → status(真实工具轨迹) → text → plan → questions → done。
无云端模型时降级:无 thinking 事件,正文一次性输出;工具步骤照常直播。
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import AsyncIterator

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AgentChatMessage, AgentChatSession, AgentRun
from app.db.session import SessionLocal
from app.llm.factory import build_llm_provider
from app.schemas.agent import AgentRunView, MenuOption, PlanningConstraints
from app.schemas.chat import ChatMessageView, ChatSessionView, ChatStreamRequest
from app.services import agent_service, planning
from app.services.context_loader import (
    MemberConstraint,
    PlanningContext,
    RecipeContext,
    ScopeNotFoundError,
    load_planning_context,
)

# 工具步骤直播节奏:每条 status 事件间隔(秒),让"进行中→完成"可感知
STEP_PACING = 0.35

CONFIRM_KEYWORDS = ("确认", "发布", "就做这套", "做这套", "就这套", "按这套")
MODIFY_KEYWORDS = ("换成", "改成", "换掉", "去掉", "再加一个", "换一个")

EVENT_WARN_PREFIX = "⚠ 不建议"
EVENT_FORBIDDEN_PREFIX = "⛔ 禁忌"

SYSTEM_PROMPT = (
    "你是家庭厨房助手 Mina。回复时可以自然地自称 Mina，但不要每句话都重复名字。"
    "基于给定的确定性规划结果,用简体中文向用户简短回复。"
    "规则:结果先于过程;点名菜品被保留要明说;有冲突警示必须引用具体成员与事件;"
    "金额来源是市区大型超市参考价;结尾自然带出下一步建议。不要编造菜单以外的数据。"
)

ROUTER_PROMPT = (
    "你是智能厨房助手的对话路由器。判断用户消息是否需要厨房业务能力。"
    "kitchen_qa:食材或菜谱知识问答，如保存、挑选、营养、做法、替代、能不能吃；"
    "kitchen_recipe:用户明确点名想吃或想做一道菜，只需要这道菜的详细做法，"
    "即使这道菜不在本地菜谱库中也属于此类；"
    "kitchen_plan:安排一餐、配餐、冰箱规划、采购、用餐人数、预算、口味、忌口、过敏；"
    "general:问候、闲聊、天气、身份、感谢或与厨房无关的话题。"
    "只输出 JSON，不要 markdown：{\"route\":\"kitchen_qa\"或\"kitchen_recipe\"或\"kitchen_plan\"或\"general\"}。"
)

GENERAL_PROMPT = (
    "你是家庭厨房助手 Mina。用户当前的问题不需要读取冰箱、家庭档案或执行配餐工具。"
    "当用户问你是谁或自然需要自我介绍时，请说自己叫 Mina。"
    "请用简短、自然的中文回答。天气、新闻等实时信息如果没有对应工具，不要编造，"
    "直接说明当前无法获取实时数据，并自然地告诉用户你能帮助安排饮食。"
)

QA_PROMPT = (
    "你是家庭厨房助手 Mina，也是一名饮食顾问。用户当前是在咨询食材或菜谱知识，"
    "需要自我介绍时请说自己叫 Mina。"
    "请允许使用你的通用知识，用简体中文给出准确、简洁、可执行的回答。"
    "可以说明保存方法、挑选方式、常见做法、营养特点、食材替代和注意事项。"
    "不要编造用户的冰箱库存、家庭成员档案或实时数据；没有实时工具时不要假装知道天气。"
)


@dataclass
class _Intent:
    kind: str  # create / modify / confirm
    named_recipes: list[RecipeContext] = field(default_factory=list)
    diners: int | None = None
    budget_cents: int | None = None
    strategy: str | None = None


def _message_without_frontend_context(text: str) -> str:
    """前端会附加本次用餐人员上下文,路由时只判断用户真正输入的内容。"""
    return text.split("\n\n[本次用餐", 1)[0].strip()


def _fallback_route(text: str) -> str:
    if any(key in text for key in CONFIRM_KEYWORDS + MODIFY_KEYWORDS):
        return "kitchen_plan"
    if re.search(r"天气|气温|下雨|晴天|阴天", text):
        return "general"
    qa_terms = (
        "怎么",
        "如何",
        "为什么",
        "能不能",
        "可不可以",
        "保存",
        "保鲜",
        "挑选",
        "区别",
        "营养",
        "热量",
        "是什么",
        "做法",
        "替代",
        "放多久",
        "怎么做",
        "能做什么",
        "什么菜",
    )
    plan_terms = (
        "吃",
        "做饭",
        "做菜",
        "冰箱",
        "配餐",
        "早餐",
        "午餐",
        "晚餐",
        "夜宵",
        "采购",
        "买菜",
        "忌口",
        "过敏",
        "预算",
        "口味",
        "烹饪",
        "下厨",
    )
    recipe_terms = ("想吃", "想做", "要做", "做个", "做一道", "来个", "来一份")
    plan_explicit = ("方案", "安排", "配餐", "菜单", "采购", "几道菜", "预算")
    if any(term in text for term in recipe_terms) and not any(term in text for term in plan_explicit):
        return "kitchen_recipe"
    if any(term in text for term in qa_terms):
        return "kitchen_qa"
    if any(term in text for term in plan_terms):
        return "kitchen_plan"
    if "食材" in text or "菜谱" in text:
        return "kitchen_qa"
    return "general"


async def _route_message(text: str) -> str:
    """优先由模型判断;无模型或路由失败时使用后端保底判断。"""
    fallback = _fallback_route(text)
    provider = build_llm_provider(get_settings())
    if provider is None:
        return fallback
    try:
        raw = await provider.chat(
            messages=[
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": text},
            ]
        )
        match = re.search(r"\{.*?\}", raw, re.S)
        if match:
            route = json.loads(match.group(0)).get("route")
            if route in {"kitchen_qa", "kitchen_recipe", "kitchen_plan", "general"}:
                return route
    except Exception:
        pass
    return fallback


def _fallback_general_text(text: str) -> str:
    if re.search(r"天气|气温|下雨|晴天|阴天", text):
        return "我目前还没有接入实时天气服务，不能可靠地播报今天的天气。不过我可以根据你想吃的口味、身体状态和冰箱食材，帮你安排一餐。"
    if re.search(r"你好|嗨|您好|早上好|晚上好", text):
        return "你好，我是 Mina，你的家庭厨房助手。告诉我今天几个人吃、想吃什么，或者直接选择本次用餐人员，我来帮你安排。"
    if re.search(r"谢谢|感谢", text):
        return "不客气。需要安排下一餐时，随时告诉我。"
    return "我会优先处理和家庭饮食、做饭与采购相关的事情。你可以告诉我今天想吃什么，或问我一道菜怎么做。"


def _fallback_qa_text(text: str) -> str:
    if re.search(r"保存|保鲜|放多久", text):
        return "可以告诉我具体食材和保存场景（常温、冷藏或冷冻），我会按食材特性给出保存建议。"
    if re.search(r"怎么做|做法|菜谱", text):
        return "可以告诉我食材、口味和人数，我会给出适合的做法与用量。"
    return "可以继续告诉我具体食材或菜名，我会从保存、挑选、做法、营养和替代方式等方面为你解答。"


def _extract_diners(text: str) -> int | None:
    if re.search(r"我们俩|两个人|我俩|两人", text):
        return 2
    if re.search(r"就我自己|我自己|一个人|我一人|单独", text):
        return 1
    match = re.search(r"(\d+)\s*人", text)
    return int(match.group(1)) if match else None


def _extract_budget_cents(text: str) -> int | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)
    if not matches:
        return None
    return int(float(matches[-1]) * 100)


def _normalize_request_text(text: str) -> str:
    """把家庭口语归一成 create_run 规则解析能识别的表达(我们俩→2人,60块→预算60元)。"""
    normalized = re.sub(r"我们俩|两个人|我俩|两人", "2人", text)
    normalized = re.sub(r"就我自己|我自己|一个人|我一人|单独", "1人", normalized)
    normalized = re.sub(r"(\d+(?:\.\d+)?)\s*块", r"\1元", normalized)
    normalized = re.sub(r"预算\s*(\d+(?:\.\d+)?)\s*元", r"预算\1元", normalized)
    normalized = re.sub(r"(?<!预算)(?<!\d)(\d+(?:\.\d+)?)\s*元", r"预算\1元", normalized)
    return normalized


def _detect_named_recipes(text: str, context: PlanningContext) -> list[RecipeContext]:
    named = [recipe for recipe in context.recipes if recipe.name in text]
    if not named and "焖面" in text:
        named = [recipe for recipe in context.recipes if "焖面" in recipe.name]
    return sorted(named, key=lambda item: text.find(item.name) if item.name in text else len(text))


def _is_direct_recipe_request(text: str, intent: _Intent) -> bool:
    if intent.budget_cents is not None:
        return False
    if any(term in text for term in ("方案", "安排", "配餐", "采购", "几道菜", "菜单")):
        return False
    return any(term in text for term in ("想吃", "想做", "怎么做", "做法", "做个", "要做"))


def _dish_name_from_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^(我想吃|我想做|我想要|想吃|想做|要做|做个|做一道|来个|来一份)\s*", "", cleaned)
    cleaned = re.sub(r"(怎么做|做法|的做法|给我做法).*?$", "", cleaned).strip(" ，,。！？?!")
    return cleaned or "这道菜"


def _generic_recipe_prompt(dish_name: str, context: PlanningContext) -> str:
    allergy_lines = [
        constraint.summary
        for constraint in context.member_constraints
        if constraint.kind == "restriction" and constraint.level == "forbidden"
    ]
    dislike_lines = [
        constraint.summary
        for constraint in context.member_constraints
        if constraint.kind == "restriction" and constraint.level == "warn"
    ]
    return (
        "你是家庭厨房助手 Mina。用户想做一道不在本地菜谱库中的菜，请用你的通用知识给出可靠、详细、可操作的做法。"
        "不要生成多个方案，也不要把问题改成配餐规划。回答包含：适合家常制作的食材用量、准备工作、"
        "分步骤烹饪、火候时间、成菜判断，以及针对成员忌口的少放/替换/分装建议。"
        "过敏原是绝对红线，不能在做法或替代建议中使用。开头简短说明这是通用做法，未使用本地菜谱库。\n\n"
        f"菜名：{dish_name}\n"
        f"当前家庭过敏红线：{'；'.join(allergy_lines) or '无'}\n"
        f"当前家庭普通忌口：{'；'.join(dislike_lines) or '无'}"
    )


def _fallback_generic_recipe_text(dish_name: str) -> str:
    return (
        f"我暂时没有《{dish_name}》的本地标准菜谱，暂时不能在无模型时可靠生成详细步骤。"
        "你可以稍后重试，或先到下厨房查看通用做法。"
    )


def _recipe_qa_prompt(recipe: RecipeContext, context: PlanningContext, diners: int) -> str:
    allergy_lines: list[str] = []
    dislike_lines: list[str] = []
    for constraint in context.member_constraints:
        if constraint.kind != "restriction" or not constraint.ingredient_key:
            continue
        if constraint.level == "forbidden":
            allergy_lines.append(constraint.summary)
        else:
            dislike_lines.append(constraint.summary)
    ingredients = "、".join(
        f"{line.name} {line.quantity * diners / max(recipe.servings, 1):g}{line.unit}"
        for line in recipe.ingredients
    ) or "按菜谱默认用量"
    return (
        "你是家庭厨房助手 Mina。用户明确想做一道菜，请直接给详细做法，不要生成多个方案或推荐其他菜。"
        "先判断过敏红线：红线食材绝对不能出现；普通忌口可以给出少放、替换或分装建议。"
        "回答要包含：适合本次人数的食材用量、准备工作、分步骤烹饪、火候与时间、"
        "针对家庭成员忌口的调整建议。\n\n"
        f"菜名：{recipe.name}\n用餐人数：{diners}\n菜谱原料：{ingredients}\n"
        f"标准步骤：{'；'.join(recipe.steps) or '请根据菜名给出可靠做法'}\n"
        f"过敏红线：{'；'.join(allergy_lines) or '无'}\n"
        f"普通忌口：{'；'.join(dislike_lines) or '无'}"
    )


def _fallback_recipe_text(recipe: RecipeContext, diners: int) -> str:
    ingredients = "、".join(
        f"{line.name} {line.quantity * diners / max(recipe.servings, 1):g}{line.unit}"
        for line in recipe.ingredients
    ) or "按菜谱默认用量"
    steps = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(recipe.steps))
    return f"## {recipe.name}\n\n**食材用量（{diners}人）**：{ingredients}\n\n**详细步骤**：\n{steps or '请按常规做法准备并烹饪。'}"


def _detect_intent(
    text: str, context: PlanningContext, has_previous_run: bool
) -> _Intent:
    if any(key in text for key in CONFIRM_KEYWORDS) and has_previous_run:
        strategy = None
        for title in ("临期优先", "原方案优先", "综合评估优先"):
            if title in text:
                strategy = title
                break
        return _Intent(kind="confirm", strategy=strategy)
    if any(key in text for key in MODIFY_KEYWORDS) and has_previous_run:
        return _Intent(
            kind="modify",
            named_recipes=_detect_named_recipes(text, context),
            diners=_extract_diners(text),
            budget_cents=_extract_budget_cents(text),
        )
    return _Intent(
        kind="create",
        named_recipes=_detect_named_recipes(text, context),
        diners=_extract_diners(text),
        budget_cents=_extract_budget_cents(text),
    )


def _recipe_by_name(context: PlanningContext, name: str) -> RecipeContext | None:
    for recipe in context.recipes:
        if recipe.name == name:
            return recipe
    return None


def _apply_named_dishes(
    run: AgentRunView, context: PlanningContext, named_recipes: list[RecipeContext]
) -> None:
    """点名菜注入主推荐;过敏禁忌默认不入菜单(回复中说明,由用户确认风险)。"""
    for named in named_recipes:
        conflict = _conflict_for(named, context)
        if conflict is not None and conflict[1] == "forbidden":
            continue
        _force_named_dish(run, context, named)


def _conflict_for(
    recipe: RecipeContext, context: PlanningContext
) -> tuple[MemberConstraint, str] | None:
    """返回(约束, 级别)。过敏原=forbidden;特殊事件口味冲突与忌口=warn。"""
    used_keys = {line.key for line in recipe.ingredients}
    for constraint in context.member_constraints:
        if (
            constraint.kind == "restriction"
            and constraint.level == "forbidden"
            and constraint.ingredient_key in used_keys
        ):
            return constraint, "forbidden"
    for constraint in context.member_constraints:
        if constraint.kind == "event" and set(recipe.taste_tags) & set(constraint.avoid_tags):
            return constraint, "warn"
    for constraint in context.member_constraints:
        if (
            constraint.kind == "restriction"
            and constraint.level == "warn"
            and constraint.ingredient_key in used_keys
        ):
            return constraint, "warn"
    return None


def _option_warnings(
    option: MenuOption, context: PlanningContext
) -> list[str]:
    warnings: list[str] = []
    for item in option.items:
        recipe = _recipe_by_name(context, str(item.get("name", "")))
        if recipe is None:
            continue
        conflict = _conflict_for(recipe, context)
        if conflict is None:
            continue
        constraint, level = conflict
        prefix = EVENT_FORBIDDEN_PREFIX if level == "forbidden" else EVENT_WARN_PREFIX
        warnings.append(f"{prefix}:{recipe.name}——{constraint.summary}")
    return warnings


def _force_named_dish(
    run: AgentRunView, context: PlanningContext, named: RecipeContext
) -> None:
    """把点名菜强制注入主推荐:替换主推荐最后一道,并按人数重算用量/成本/缺口。"""
    option = run.options[0]
    if any(item.get("name") == named.name for item in option.items):
        return
    keep_names = [item.get("name") for item in option.items[: len(option.items) - 1]]
    chosen = [named]
    for name in keep_names:
        recipe = _recipe_by_name(context, str(name))
        if recipe is not None:
            chosen.append(recipe)
    diners = run.constraints.expected_diners or context.expected_diners
    requirements = planning.compute_requirements(chosen, diners)
    key_names = planning.build_key_names(context)
    option.procurement_list = planning.procurement_lines(requirements, context, key_names)
    total_cost, total_kcal = planning.estimate_totals(chosen, diners)
    option.estimated_cost_cents = total_cost
    option.estimated_kcal_per_serving = (
        int(total_kcal / diners) if total_kcal and diners else option.estimated_kcal_per_serving
    )
    option.items = [
        {
            "name": recipe.name,
            "servings": diners,
            "kcal_per_serving": recipe.kcal_per_serving,
        }
        for recipe in chosen
    ]
    _persist_options(run.id, run.options)


def _persist_options(run_id: str, options: list[MenuOption]) -> None:
    with SessionLocal() as session:
        row = session.get(AgentRun, run_id)
        if row is not None:
            row.state = dict(row.state or {})
            row.state["options"] = [option.model_dump() for option in options]
            session.commit()


def _latest_run_id(workspace_id: str) -> str | None:
    with SessionLocal() as session:
        row = session.scalar(
            select(AgentRun.id)
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        return row


def _money(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"{cents / 100:.1f} 元"


def _compose_plan_text(
    run: AgentRunView, context: PlanningContext, named_recipes: list[RecipeContext]
) -> str:
    option = run.options[0]
    parts: list[str] = []
    for recipe in named_recipes:
        conflict = _conflict_for(recipe, context)
        if conflict is None:
            parts.append(f"已为你保留{recipe.name}。")
        else:
            constraint, level = conflict
            if level == "forbidden":
                parts.append(
                    f"{recipe.name}我不能直接推荐:{constraint.summary},这是过敏禁忌。"
                    "下面只提供不触碰过敏红线的方案。"
                )
            else:
                parts.append(
                    f"{recipe.name}可以照常做,但**不建议**:{constraint.summary},这道菜和它冲突。"
                    "食谱和用量我照常附在方案里了。"
                )

    dishes = "、".join(str(item.get("name")) for item in option.items)
    parts.append(f"初始方案参考菜品:{dishes}。切换策略后，具体菜品、费用和采购项以方案卡为准。")
    backup = " / ".join(opt.title for opt in run.options[1:])
    if backup:
        parts.append(f"备选:{backup}。")

    kcal = option.estimated_kcal_per_serving
    cost_line = f"初始方案预计总成本 {_money(option.estimated_cost_cents)}"
    if kcal:
        cost_line += f",人均约 {kcal} kcal"
    parts.append(cost_line + "(价格参考:市区大型超市公开参考价)。")

    if option.procurement_list:
        lines = "、".join(
            f"{row.get('ingredient', '')}缺 {row.get('missing_quantity', '')}"
            for row in option.procurement_list
        )
        parts.append(f"需要采购:{lines}。")
    else:
        parts.append("冰箱现有食材就够了,不用采购。")
    parts.extend(option.pantry_notes or [])

    budget = run.constraints.budget_limit_cents
    if budget:
        diff = budget - option.estimated_cost_cents
        if diff >= 0:
            parts.append(f"预算 {_money(budget)},还剩 {_money(diff)}。")
        else:
            parts.append(f"预算 {_money(budget)},超出 {_money(-diff)},主要差在采购缺口上。")

    expiring = context.expiring_keys(context.service_date)
    if expiring:
        key_names = planning.build_key_names(context)
        names = "、".join(key_names[key] for key in sorted(expiring))
        parts.append(f"这套餐优先消耗了临期食材:{names}。")
    return "\n\n".join(parts)


def _compose_confirm_text(plan_view) -> str:
    items = "、".join(str(item.get("name")) for item in plan_view.items or [])
    procurement = plan_view.procurement_list or []
    lines = [f"已确认「{plan_view.strategy}」这套,食材用量按人数落好了。"]
    if items:
        lines.append(f"菜单:{items}。")
    if procurement:
        buy = "、".join(
            f"{row.get('ingredient', '')} 缺 {row.get('missing_quantity', '')}"
            for row in procurement
        )
        lines.append(f"采购清单:{buy}。")
    lines.append("价格参考:市区大型超市公开参考价。下单前记得核对冰柜存货。")
    return "\n".join(lines)


def _alternative_questions(
    run: AgentRunView, context: PlanningContext
) -> list[str]:
    in_menu = {
        str(item.get("name")) for option in run.options for item in option.items
    }
    alternatives: list[str] = []
    for recipe in context.recipes:
        if recipe.name in in_menu:
            continue
        if _conflict_for(recipe, context) is not None:
            continue
        alternatives.append(f"试试「{recipe.name}」?")
        if len(alternatives) == 2:
            break
    return alternatives


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _llm_stream_text(
    prompt_messages: list[dict],
) -> AsyncIterator[tuple[str, str]]:
    """有云端模型时,流式产出 ("thinking"|"text", 增量)。失败时静默回退规则文本。"""
    provider = build_llm_provider(get_settings())
    if provider is None:
        return
    try:
        async for kind, delta in provider.chat_stream(messages=prompt_messages):
            if delta:
                yield kind, delta
    except Exception:
        yield "__error__", ""


async def stream_chat(payload: ChatStreamRequest) -> AsyncIterator[str]:
    settings = get_settings()
    with SessionLocal() as session:
        if payload.session_id:
            chat_session = session.get(AgentChatSession, payload.session_id)
        else:
            chat_session = None
        if chat_session is None:
            chat_session = AgentChatSession(workspace_id=payload.workspace_id)
            session.add(chat_session)
            session.flush()
        session_id = chat_session.id
        title = chat_session.title
        if title == "新会话" and payload.message:
            chat_session.title = payload.message[:20]
        session.add(
            AgentChatMessage(session_id=session_id, role="user", content=payload.message)
        )
        session.commit()

    user_text = _message_without_frontend_context(payload.message)
    route = await _route_message(user_text)
    if _fallback_route(user_text) == "kitchen_recipe" or (
        any(term in user_text for term in ("怎么做", "做法"))
        and not any(term in user_text for term in ("保存", "保鲜", "方案", "安排", "预算"))
    ):
        route = "kitchen_recipe"
    if route == "general":
        # 普通话题不读取厨房上下文,不创建规划运行,也不发送 thinking/status/plan。
        text_parts: list[str] = []
        async for kind, delta in _llm_stream_text(
            [
                {"role": "system", "content": GENERAL_PROMPT},
                {"role": "user", "content": user_text},
            ]
        ):
            if kind == "text" and delta:
                text_parts.append(delta)
                yield _sse("text", {"delta": delta})
        if not text_parts:
            text_parts = [_fallback_general_text(user_text)]
            yield _sse("text", {"delta": text_parts[0]})

        full_text = "".join(text_parts)
        message_id = None
        with SessionLocal() as session:
            message = AgentChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_text,
                thinking_text=None,
                run_id=None,
            )
            session.add(message)
            session.commit()
            session.flush()
            message_id = message.id
        yield _sse(
            "done",
            {
                "session_id": session_id,
                "message_id": message_id,
                "needs_input": False,
                "provider": settings.llm_provider if text_parts else None,
                "route": "general",
            },
        )
        return

    if route == "kitchen_qa":
        # 知识问答不读取冰箱/家庭档案,不创建规划运行,也不发送 thinking/status/plan。
        text_parts: list[str] = []
        async for kind, delta in _llm_stream_text(
            [
                {"role": "system", "content": QA_PROMPT},
                {"role": "user", "content": user_text},
            ]
        ):
            if kind == "text" and delta:
                text_parts.append(delta)
                yield _sse("text", {"delta": delta})
        if not text_parts:
            text_parts = [_fallback_qa_text(user_text)]
            yield _sse("text", {"delta": text_parts[0]})

        full_text = "".join(text_parts)
        message_id = None
        with SessionLocal() as session:
            message = AgentChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_text,
                thinking_text=None,
                run_id=None,
            )
            session.add(message)
            session.commit()
            session.flush()
            message_id = message.id
        yield _sse(
            "done",
            {
                "session_id": session_id,
                "message_id": message_id,
                "needs_input": False,
                "provider": settings.llm_provider if text_parts else None,
                "route": "kitchen_qa",
            },
        )
        return

    try:
        with SessionLocal() as session:
            context = load_planning_context(
                session,
                payload.workspace_id,
                payload.site_id,
                payload.meal_service_id,
            )
    except ScopeNotFoundError as exc:
        yield _sse("error", {"message": str(exc), "fallback": False})
        yield _sse("done", {"session_id": session_id, "message_id": None})
        return

    latest_run_id = _latest_run_id(payload.workspace_id)
    intent = _detect_intent(user_text, context, has_previous_run=bool(latest_run_id))

    if route == "kitchen_recipe" or _is_direct_recipe_request(user_text, intent):
        recipe = intent.named_recipes[0] if intent.named_recipes else None
        if recipe is None:
            dish_name = _dish_name_from_text(user_text)
            text_parts = []
            async for kind, delta in _llm_stream_text(
                [
                    {"role": "system", "content": _generic_recipe_prompt(dish_name, context)},
                    {"role": "user", "content": user_text},
                ]
            ):
                if kind == "text" and delta:
                    text_parts.append(delta)
                    yield _sse("text", {"delta": delta})
            full_text = "".join(text_parts) or _fallback_generic_recipe_text(dish_name)
            if not text_parts:
                yield _sse("text", {"delta": full_text})
            with SessionLocal() as session:
                message = AgentChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=full_text,
                    thinking_text=None,
                    run_id=None,
                )
                session.add(message)
                session.commit()
                message_id = message.id
            yield _sse("done", {
                "session_id": session_id,
                "message_id": message_id,
                "needs_input": False,
                "provider": settings.llm_provider if text_parts else None,
                "route": "kitchen_recipe",
                "search_query": dish_name,
            })
            return
        if recipe is not None:
            diners = _extract_diners(user_text) or context.expected_diners
            conflict = _conflict_for(recipe, context)
            text_parts: list[str] = []
            if conflict is not None and conflict[1] == "forbidden":
                full_text = (
                    f"这道{recipe.name}包含{conflict[0].summary}涉及的过敏原，"
                    "为了安全起见，我不能给出会使用该食材的做法。可以换一道不含该过敏原的菜。"
                )
                yield _sse("text", {"delta": full_text})
            else:
                async for kind, delta in _llm_stream_text(
                    [
                        {"role": "system", "content": _recipe_qa_prompt(recipe, context, diners)},
                        {"role": "user", "content": user_text},
                    ]
                ):
                    if kind == "text" and delta:
                        text_parts.append(delta)
                        yield _sse("text", {"delta": delta})
                if not text_parts:
                    full_text = _fallback_recipe_text(recipe, diners)
                    dislike_constraints = [
                        constraint.summary
                        for constraint in context.member_constraints
                        if constraint.kind == "restriction" and constraint.level == "warn"
                    ]
                    if dislike_constraints:
                        full_text += "\n\n**忌口调整建议**：" + "；".join(dislike_constraints) + "。相关食材建议少放、替换或单独分装。"
                    yield _sse("text", {"delta": full_text})
                else:
                    full_text = "".join(text_parts)
            message_id = None
            with SessionLocal() as session:
                message = AgentChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=full_text,
                    thinking_text=None,
                    run_id=None,
                )
                session.add(message)
                session.commit()
                session.flush()
                message_id = message.id
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "message_id": message_id,
                    "needs_input": False,
                    "provider": settings.llm_provider if text_parts else None,
                    "route": "kitchen_recipe",
                },
            )
            return

    run_view: AgentRunView | None = None
    plan_text = ""
    questions: list[str] = []
    needs_input = False
    plan_payload: dict | None = None

    if intent.kind == "confirm":
        strategy = intent.strategy or "expiring_first"
        strategy_key = strategy
        if strategy in ("临期优先", "原方案优先", "综合评估优先"):
            mapping = {
                "临期优先": "expiring_first",
                "原方案优先": "original_first",
                "综合评估优先": "balanced_first",
            }
            strategy_key = mapping[strategy]
        from app.services import meal_plan_service

        plan_view = meal_plan_service.confirm_plan(latest_run_id, strategy_key)
        plan_text = _compose_confirm_text(plan_view)
        questions = ["开始做饭吧", "看看采购清单"]
    elif intent.kind == "create" and not intent.named_recipes and intent.diners is None and intent.budget_cents is None:
        needs_input = True
        constraint_detail = (
            "；".join(constraint.summary for constraint in context.member_constraints)
            or "全家当前没有生效的忌口或特殊事件"
        )
        plan_text = (
            "好,先确认两件事:这餐几个人吃?有预算上限的话我一并算进成本和采购缺口里。"
            "全家当前的饮食限制我记着呢:" + constraint_detail + "。"
        )
        questions = ["就我自己", "两个人都在", "预算 60 元"]
    elif intent.kind == "modify" and latest_run_id:
        from app.services import agent_service as _agent_service

        run_view = await _agent_service.revise_run(
            latest_run_id, intent.diners, intent.budget_cents
        )
        if run_view is None:
            yield _sse("error", {"message": "找不到最近的方案运行", "fallback": True})
            run_view = None
        if run_view is not None:
            _apply_named_dishes(run_view, context, intent.named_recipes)
            for option in run_view.options:
                option.warnings = _option_warnings(option, context)
            plan_text = _compose_plan_text(run_view, context, intent.named_recipes)
            questions = _alternative_questions(run_view, context)
            plan_payload = run_view.model_dump()
            for trace in run_view.tool_trace:
                yield _sse(
                    "status",
                    {"step": trace.tool_name, "state": "done", "detail": trace.output_summary},
                )
    if intent.kind != "confirm" and not needs_input and (
        intent.kind == "create" or (intent.kind == "modify" and run_view is None)
    ):
        # 工具步骤直播:on_step 回调把每个工具的 开始/完成 实时推入队列,
        # 配合 STEP_PACING 节奏控制让每一步可感知(数据真实,节奏为演示效果)。
        step_queue: asyncio.Queue = asyncio.Queue()

        def on_step(state: str, tool_name: str, detail: str) -> None:
            step_queue.put_nowait(("status", {"step": tool_name, "state": state, "detail": detail}))

        def on_thinking(delta: str) -> None:
            step_queue.put_nowait(("thinking", {"delta": delta}))

        normalized = _normalize_request_text(payload.message)
        run_task = asyncio.create_task(
            agent_service.create_run(
                payload.workspace_id,
                payload.site_id,
                payload.meal_service_id,
                normalized,
                on_step=on_step,
                on_thinking=on_thinking,
            )
        )
        while not (run_task.done() and step_queue.empty()):
            try:
                event_kind, event_data = step_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
                continue
            yield _sse(event_kind, event_data)
            # 思维链实时流动不加节奏;工具步骤之间加节奏让"进行中→完成"可感知
            if event_kind == "status":
                await asyncio.sleep(STEP_PACING)
        try:
            run_view = run_task.result()
        except Exception as exc:  # noqa: BLE001 —— 任何规划失败都降级为错误事件
            yield _sse("error", {"message": f"规划失败:{exc}", "fallback": True})
            run_view = None
        if run_view is not None:
            if intent.diners or intent.budget_cents:
                constraints = run_view.constraints.model_copy(deep=True)
                if intent.diners:
                    constraints.expected_diners = intent.diners
                if intent.budget_cents:
                    constraints.budget_limit_cents = intent.budget_cents
                run_view.constraints = constraints
            _apply_named_dishes(run_view, context, intent.named_recipes)
            for option in run_view.options:
                option.warnings = _option_warnings(option, context)
            plan_text = _compose_plan_text(run_view, context, intent.named_recipes)
            questions = _alternative_questions(run_view, context)
            plan_payload = run_view.model_dump()
            _persist_options(run_view.id, run_view.options)

    # 回答流式:有云端模型时逐字输出;规则模式一次性给出(前端本地补打字机)
    llm_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"用户说:{payload.message}\n\n规划结果:\n{plan_text}"},
    ]
    text_streamed = False
    thinking_parts: list[str] = []
    text_parts: list[str] = []
    async for kind, delta in _llm_stream_text(llm_messages):
        if kind == "__error__":
            break
        if kind == "thinking":
            thinking_parts.append(delta)
            yield _sse("thinking", {"delta": delta})
        else:
            text_streamed = True
            text_parts.append(delta)
            yield _sse("text", {"delta": delta})
    if not text_streamed:
        text_parts = [plan_text]
        yield _sse("text", {"delta": plan_text})

    full_text = "".join(text_parts) or plan_text

    if plan_payload is not None:
        # 菜单项附带菜谱 ID,前端展开食谱详情用
        recipe_ids = {recipe.name: recipe.id for recipe in context.recipes}
        for option in plan_payload["options"]:
            for item in option["items"]:
                item["recipe_id"] = recipe_ids.get(str(item.get("name")))
        yield _sse("plan", plan_payload)
    if questions:
        yield _sse("questions", {"items": questions, "needs_input": needs_input})

    # 持久化助手消息(含思维链回看与关联运行)
    message_id = None
    with SessionLocal() as session:
        message = AgentChatMessage(
            session_id=session_id,
            role="assistant",
            content=full_text,
            thinking_text="".join(thinking_parts) or None,
            run_id=run_view.id if run_view else None,
        )
        session.add(message)
        session.commit()
        session.flush()
        message_id = message.id

    yield _sse(
        "done",
        {
            "session_id": session_id,
            "message_id": message_id,
            "needs_input": needs_input,
            "provider": settings.llm_provider if text_streamed else None,
        },
    )


def get_session_view(session_id: str) -> ChatSessionView | None:
    with SessionLocal() as session:
        chat_session = session.get(AgentChatSession, session_id)
        if chat_session is None:
            return None
        rows = session.scalars(
            select(AgentChatMessage)
            .where(AgentChatMessage.session_id == session_id)
            .order_by(AgentChatMessage.created_at)
        ).all()
        return ChatSessionView(
            session_id=chat_session.id,
            title=chat_session.title,
            messages=[
                ChatMessageView(
                    id=row.id,
                    role=row.role,
                    content=row.content,
                    thinking_text=row.thinking_text,
                    run_id=row.run_id,
                )
                for row in rows
            ],
        )
