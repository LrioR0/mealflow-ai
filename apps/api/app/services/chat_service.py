"""对话编排服务:意图路由、约束前置、点名菜冲突检测、流式事件生成。

事件协议(docs/V2改造方案 §8.1):thinking → status(真实工具轨迹) → text → plan → questions → done。
无云端模型时降级:无 thinking 事件,正文一次性输出;工具步骤照常直播。
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import AsyncIterator

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AgentChatMessage, AgentChatSession, AgentRun
from app.db.session import SessionLocal
from app.llm.factory import build_llm_provider
from app.schemas.agent import AgentRunView, MenuOption, PlanningConstraints
from app.schemas.chat import (
    ChatMessageView,
    ChatSessionSummary,
    ChatSessionView,
    ChatStreamRequest,
)
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
    "\n\n[菜名标注规则]只要回复中出现具体菜名（例如推荐了菜品、提到了某道菜的做法），"
    "就必须在回复的最后一行单独输出<dishes>菜名1|菜名2</dishes>，最多3个菜名，用|分隔，"
    "例如:<dishes>番茄炒蛋|青椒肉丝</dishes>。整条回复没有具体菜名时才允许省略此行。"
)

QA_PROMPT = (
    "你是家庭厨房助手 Mina，也是一名饮食顾问。用户当前是在咨询食材或菜谱知识，"
    "需要自我介绍时请说自己叫 Mina。"
    "请允许使用你的通用知识，用简体中文给出准确、简洁、可执行的回答。"
    "可以说明保存方法、挑选方式、常见做法、营养特点、食材替代和注意事项。"
    "不要编造用户的冰箱库存、家庭成员档案或实时数据；没有实时工具时不要假装知道天气。"
    "\n\n[菜名标注规则]只要回复中出现具体菜名（例如推荐了菜品、列举了某道菜的做法），"
    "就必须在回复的最后一行单独输出<dishes>菜名1|菜名2</dishes>，最多3个菜名，用|分隔，"
    "例如:<dishes>番茄炒蛋|青椒肉丝</dishes>。整条回复没有具体菜名时才允许省略此行。"
)

_DISH_TAG_REMINDER = (
    "再次提醒:若本轮回复中出现任何具体菜名，在最后一行单独输出<dishes>菜名1|菜名2</dishes>"
    "(最多3个,以<dishes>开头、以</dishes>结尾);没有具体菜名则不输出该行。"
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


_FOOD_QUERY_STRIP_PATTERNS = (
    # 后缀诉求与语气词
    r"给(我|你)?(几个|一个|个)?(详细|具体)?(的)?(做法|方案|菜谱|教程|建议)",
    r"几个(方案|菜|做法|建议)",
    r"(吧|哈|呗|呀|啊|呢|哦|啦)+",
    # 预算金额
    r"(预算|花|不超过)?\s*\d+(\.\d+)?\s*(块钱|元|块)",
    # 时间状语(日期词与时段词分开剥,避免「今晚虾」这类无时段组合漏剥)
    r"((今|明|后|昨)天|(今|明|后)晚|明早|今晚)(早上|早晨|上午|中午|下午|傍晚|晚上|夜里|半夜)?",
    r"^(早上|早晨|上午|中午|下午|傍晚|晚上|夜里|半夜)",
    # 用餐人称
    r"(我们俩|两个人|我俩|两人|大家|就我自己|我自己|我一个人|我一人|一个人|帮我)",
    # 动词短语(放最后,避免先把「吃」从「想吃」里单独剥走)
    r"(想吃点|想吃|想做个|想做|想来点|想要|要吃|要做|来一份|来份|来个|来点|做个|做一道|吃点|安排)",
)


def _extract_food_query(text: str) -> str:
    """从口语里剥出核心食材/菜名词条:今晚想吃虾 → 虾。迭代清洗到稳定为止。"""
    cleaned = text.strip()
    for _ in range(6):
        before = cleaned
        for pattern in _FOOD_QUERY_STRIP_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned)
        cleaned = cleaned.strip(" ，,。！？?！、;；:：\n")
        if cleaned == before:
            break
    return cleaned


def _key_name_map(context: PlanningContext) -> dict[str, str]:
    """ingredient key → 中文名(库存+全部菜谱配料),用于把约束 summary 里裸露的 key 翻译成人话。"""
    names: dict[str, str] = {line.key: line.name for line in context.inventory}
    for recipe in context.recipes:
        for line in recipe.ingredients:
            names.setdefault(line.key, line.name)
    return names


def _fridge_usage(
    recipe: RecipeContext, inv_keys: set[str], expiring: set[str]
) -> tuple[list[str], list[str], list[str]]:
    """返回(用到的库存食材名, 其中临期的, 缺的必需食材名)。可选配料不计入缺口。"""
    used: list[str] = []
    expiring_used: list[str] = []
    missing: list[str] = []
    for line in recipe.ingredients:
        if line.key in inv_keys:
            used.append(line.name)
            if line.key in expiring:
                expiring_used.append(line.name)
        elif not line.optional:
            missing.append(line.name)
    return used, expiring_used, missing


def _candidate_item(
    recipe: RecipeContext,
    context: PlanningContext,
    key_names: dict[str, str],
    used: list[str],
    expiring_used: list[str],
    missing: list[str],
) -> dict:
    conflict = _conflict_for(recipe, context)
    conflict_summary = None
    if conflict is not None:
        conflict_summary = conflict[0].summary
        key = conflict[0].ingredient_key
        if key and key in key_names:
            conflict_summary = conflict_summary.replace(key, key_names[key])
    names = [line.name for line in recipe.ingredients]
    return {
        "recipe_id": recipe.id,
        "name": recipe.name,
        "ingredients_summary": "、".join(names[:4]) + ("等" if len(names) > 4 else ""),
        "conflict_level": conflict[1] if conflict else None,
        "conflict_summary": conflict_summary,
        "expiring": bool(expiring_used),
        "expiring_used": expiring_used,
        "used_fridge": used,
        "missing": missing,
    }


def _recall_recipes_by_ingredient(
    query: str, context: PlanningContext
) -> tuple[list[dict], int]:
    """食材模糊召回:任一配料名与 query 双向包含即命中(虾↔虾仁)。

    主料命中优先、临期食材加权;不做忌口过滤——冲突由 candidates 事件的
    conflict 字段交给前端标注(展示不隐藏)。返回(前6条, 总命中数)。
    """
    term = query.strip()
    if not term:
        return [], 0
    expiring = context.expiring_keys(date.today())
    key_names = _key_name_map(context)
    inv_keys = {line.key for line in context.inventory if line.quantity > 0}
    scored: list[tuple[tuple[int, int, int], RecipeContext, list[str], list[str], list[str]]] = []
    for recipe in context.recipes:
        hit_lines = [line for line in recipe.ingredients if term in line.name or line.name in term]
        if not hit_lines:
            continue
        main_hit = any(not line.optional for line in hit_lines)
        used, expiring_used, missing = _fridge_usage(recipe, inv_keys, expiring)
        score = (2 if main_hit else 1, 1 if expiring_used else 0, -len(hit_lines))
        scored.append((score, recipe, used, expiring_used, missing))
    scored.sort(key=lambda item: item[0], reverse=True)
    items = [
        _candidate_item(recipe, context, key_names, used, expiring_used, missing)
        for _, recipe, used, expiring_used, missing in scored[:6]
    ]
    return items, len(scored)


def _looks_like_inventory_menu(text: str) -> bool:
    """冰箱/库存 + 要菜单/能做什么类诉求 → 库存驱动菜单分支(Agent 自读冰箱)。"""
    has_source = "冰箱" in text or "库存" in text
    wants_menu = any(
        term in text
        for term in ("菜单", "什么菜", "能做", "做菜", "做饭", "做什么", "吃什么", "吃", "推荐", "生成", "选", "临期", "适合", "安排")
    )
    return has_source and wants_menu


def _build_inventory_menu(context: PlanningContext) -> tuple[list[dict], int]:
    """按冰箱库存出候选菜单:用到临期食材的排最前,库存覆盖度次之(缺口越少越前)。

    只收录至少用到一种冰箱必需食材的菜;同样不做忌口过滤,仅标注。返回(前6条, 总数)。
    """
    expiring = context.expiring_keys(date.today())
    key_names = _key_name_map(context)
    inv_keys = {line.key for line in context.inventory if line.quantity > 0}
    scored: list[tuple[tuple[int, float, int], RecipeContext, list[str], list[str], list[str]]] = []
    for recipe in context.recipes:
        used, expiring_used, missing = _fridge_usage(recipe, inv_keys, expiring)
        required_hits = any(
            line.key in inv_keys for line in recipe.ingredients if not line.optional
        )
        if not required_hits:
            continue
        required = [line for line in recipe.ingredients if not line.optional]
        coverage = (len(required) - len(missing)) / len(required) if required else 1.0
        score = (len(expiring_used), round(coverage, 2), len(used))
        scored.append((score, recipe, used, expiring_used, missing))
    scored.sort(key=lambda item: item[0], reverse=True)
    items = [
        _candidate_item(recipe, context, key_names, used, expiring_used, missing)
        for _, recipe, used, expiring_used, missing in scored[:6]
    ]
    return items, len(scored)


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


_DISH_TAG_OPEN = "<dishes>"
_DISH_TAG_CLOSE = "</dishes>"


class _DishTagFilter:
    """流式剥离模型输出的 <dishes>菜名1|菜名2</dishes> 标记行。

    实测模型经常漏写开启标签,因此解析以闭合标签为准:完整行里出现
    </dishes> 就把该行当标记行吞掉并解析菜名;开启标签存在时同样处理。
    未换行的尾部先扣住,拼成完整行再判定,流式粒度为按行。
    """

    def __init__(self) -> None:
        self.dishes: list[str] = []
        self._pending = ""  # 尚未见到换行的尾部内容
        self._holding = False  # 已见开启标签,正在等闭合
        self._hold_buf = ""

    def _parse_names(self, raw: str) -> None:
        for part in raw.replace("\n", "|").split("|"):
            part = part.strip()
            for sep in (":", "："):
                if sep in part:
                    part = part.rsplit(sep, 1)[1].strip()
            if part:
                self.dishes.append(part)
            if len(self.dishes) >= 3:
                return

    def _consume_line(self, line: str) -> str:
        """处理一条完整行(含换行),返回应放行的文本。"""
        if self._holding:
            if _DISH_TAG_CLOSE in line:
                names_raw, _, after = line.partition(_DISH_TAG_CLOSE)
                self._parse_names((self._hold_buf + names_raw).strip())
                self._hold_buf = ""
                self._holding = False
                return after
            self._hold_buf += line
            return ""
        idx = line.find(_DISH_TAG_OPEN)
        if idx != -1:
            before = line[:idx]
            rest = line[idx + len(_DISH_TAG_OPEN) :]
            end = rest.find(_DISH_TAG_CLOSE)
            if end != -1:
                self._parse_names(rest[:end])
                return before + rest[end + len(_DISH_TAG_CLOSE) :]
            self._holding = True
            self._hold_buf = rest
            return before
        end = line.find(_DISH_TAG_CLOSE)
        if end != -1:
            # 观测到的退化形态:只有"菜名1|菜名2</dishes>"
            self._parse_names(line[:end])
            return line[end + len(_DISH_TAG_CLOSE) :]
        return line

    def feed(self, delta: str) -> str:
        self._pending += delta
        out: list[str] = []
        while "\n" in self._pending:
            nl = self._pending.find("\n")
            line = self._pending[: nl + 1]
            self._pending = self._pending[nl + 1 :]
            out.append(self._consume_line(line))
        if self._holding:
            self._hold_buf += self._pending
            self._pending = ""
        return "".join(out)

    def flush(self) -> str:
        """流结束:最后一行按完整行判定;普通文本放行,残缺标记宽容解析后丢弃。"""
        line, self._pending = self._pending, ""
        if self._holding:
            merged = (self._hold_buf + line).strip()
            if _DISH_TAG_CLOSE in merged:
                self._parse_names(merged.split(_DISH_TAG_CLOSE)[0].strip())
            elif merged:
                self._parse_names(merged)
            self._hold_buf = ""
            self._holding = False
            return ""
        if not line:
            return ""
        return self._consume_line(line + "\n").rstrip("\n")


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


_HISTORY_MAX_MESSAGES = 8
_HISTORY_MAX_CHARS = 4000


def _recent_history_messages(
    session_id: str | None, exclude_message_id: str | None
) -> list[dict[str, str]]:
    """多轮上下文:取本会话最近几条历史消息,超预算从最旧的开始丢弃。

    当轮用户消息在调用前已落库,用 exclude_message_id 排除避免重复。
    """
    if not session_id:
        return []
    with SessionLocal() as session:
        rows = session.scalars(
            select(AgentChatMessage)
            .where(AgentChatMessage.session_id == session_id)
            .order_by(AgentChatMessage.created_at.desc())
            .limit(40)
        ).all()
    history: list[dict[str, str]] = []
    for row in rows:
        if exclude_message_id and row.id == exclude_message_id:
            continue
        content = (row.content or "").strip()
        if not content:
            continue
        if row.role == "user":
            content = _message_without_frontend_context(content)
            if not content:
                continue
        history.append(
            {"role": "user" if row.role == "user" else "assistant", "content": content}
        )
        if len(history) >= _HISTORY_MAX_MESSAGES:
            break
    history.reverse()
    total_chars = sum(len(item["content"]) for item in history)
    while history and total_chars > _HISTORY_MAX_CHARS:
        total_chars -= len(history[0]["content"])
        history.pop(0)
    return history


async def stream_chat(payload: ChatStreamRequest) -> AsyncIterator[str]:
    settings = get_settings()
    current_user_message_id: str | None = None
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
            # 标题取用户输入主行,剥掉前端附带的 [本次用餐…] 上下文行再截断
            main_line = payload.message.split("\n")[0].strip()
            chat_session.title = main_line[:20] if main_line else "新会话"
        current_user_message = AgentChatMessage(
            session_id=session_id, role="user", content=payload.message
        )
        session.add(current_user_message)
        session.flush()
        current_user_message_id = current_user_message.id
        session.commit()

    user_text = _message_without_frontend_context(payload.message)
    route = await _route_message(user_text)
    if _fallback_route(user_text) == "kitchen_recipe" or (
        any(term in user_text for term in ("怎么做", "做法"))
        and not any(term in user_text for term in ("保存", "保鲜", "方案", "安排", "预算"))
    ):
        route = "kitchen_recipe"
    if route in ("kitchen_plan", "kitchen_qa") and _looks_like_inventory_menu(user_text):
        # 库存驱动菜单:Agent 自己读冰箱出候选列表,不再反问用户冰箱里有什么
        route = "kitchen_inventory"
    if route == "kitchen_plan":
        # 配餐规划分支已下线(C端定位为对话式做菜助手):
        # 有明确做菜意图的进单菜做法分支,其余按厨房问答对话处理
        route = (
            "kitchen_recipe"
            if any(
                term in user_text
                for term in ("想吃", "想做", "要做", "做个", "做一道", "来个", "来一份", "怎么做", "做法")
            )
            else "kitchen_qa"
        )
    if route == "general":
        # 普通话题不读取厨房上下文,不创建规划运行,也不发送 thinking/status/plan。
        text_parts: list[str] = []
        dish_filter = _DishTagFilter()
        async for kind, delta in _llm_stream_text(
            [
                {"role": "system", "content": GENERAL_PROMPT},
                *_recent_history_messages(session_id, current_user_message_id),
                {"role": "user", "content": user_text},
                {"role": "system", "content": _DISH_TAG_REMINDER},
            ]
        ):
            if kind == "text" and delta:
                safe = dish_filter.feed(delta)
                if safe:
                    text_parts.append(safe)
                    yield _sse("text", {"delta": safe})
        tail = dish_filter.flush()
        if tail:
            text_parts.append(tail)
            yield _sse("text", {"delta": tail})
        if not text_parts:
            text_parts = [_fallback_general_text(user_text)]
            yield _sse("text", {"delta": text_parts[0]})

        full_text = "".join(text_parts).rstrip()
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
                "search_queries": dish_filter.dishes,
            },
        )
        return

    if route == "kitchen_qa":
        # 知识问答不读取冰箱/家庭档案,不创建规划运行,也不发送 thinking/status/plan。
        text_parts: list[str] = []
        dish_filter = _DishTagFilter()
        async for kind, delta in _llm_stream_text(
            [
                {"role": "system", "content": QA_PROMPT},
                *_recent_history_messages(session_id, current_user_message_id),
                {"role": "user", "content": user_text},
                {"role": "system", "content": _DISH_TAG_REMINDER},
            ]
        ):
            if kind == "text" and delta:
                safe = dish_filter.feed(delta)
                if safe:
                    text_parts.append(safe)
                    yield _sse("text", {"delta": safe})
        tail = dish_filter.flush()
        if tail:
            text_parts.append(tail)
            yield _sse("text", {"delta": tail})
        if not text_parts:
            text_parts = [_fallback_qa_text(user_text)]
            yield _sse("text", {"delta": text_parts[0]})

        full_text = "".join(text_parts).rstrip()
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
                "search_queries": dish_filter.dishes,
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

    if route == "kitchen_inventory":
        # 库存菜单:纯规则生成(不依赖 LLM),临期优先;忌口只标注不过滤
        menu_items, menu_total = _build_inventory_menu(context)
        thinking_log = ""
        if menu_items:
            today = date.today()
            expiring_names = sorted(
                line.name
                for line in context.inventory
                if line.quantity > 0 and line.key in context.expiring_keys(today)
            )
            in_stock = sum(1 for line in context.inventory if line.quantity > 0)
            # 合成思考过程:真实的库存读取与排序依据(本地计算,不做人为延迟)
            inventory_thinking = (
                f"【读取冰箱】{in_stock} 种食材在库"
                + (f"，其中 {'、'.join(expiring_names)} {len(expiring_names)} 项临期" if expiring_names else "")
                + "\n"
                + f"【召回排序】按「临期使用数 → 库存覆盖度 → 用料数」从 {menu_total} 道库内菜挑出 {len(menu_items)} 道\n"
                + "【忌口检查】冲突只标注不过滤，决定权在你\n"
            )
            thinking_log = inventory_thinking
            for chunk in inventory_thinking.splitlines():
                if chunk:
                    yield _sse("thinking", {"delta": chunk + "\n"})
            stock_names = [
                f"{line.name}（临期）" if line.key in context.expiring_keys(today) else line.name
                for line in context.inventory
                if line.quantity > 0
            ]
            lead_text = (
                "我看了下冰箱，现有："
                + "、".join(stock_names)
                + "。"
                + f"结合库存给你挑了 {len(menu_items)} 道菜"
                + (f"（共 {menu_total} 道，先展示最相关的 {len(menu_items)} 道）" if menu_total > len(menu_items) else "")
                + "，用到临期食材的排在了前面，点击菜名查看按当前人数换算的做法。"
                "标红的含你的过敏原、标黄的撞上当前忌口或状态，仅供参考，仍可查看。"
            )
            yield _sse(
                "candidates",
                {"query": "冰箱库存", "total": menu_total, "items": menu_items},
            )
        else:
            lead_text = (
                "我看了下冰箱，现有食材还凑不出菜谱库里的菜。"
                "先补点货，或者直接告诉我你想吃的菜，我来给做法。"
            )
        yield _sse("text", {"delta": lead_text})
        with SessionLocal() as session:
            message = AgentChatMessage(
                session_id=session_id,
                role="assistant",
                content=lead_text,
                thinking_text=thinking_log or None,
                run_id=None,
            )
            session.add(message)
            session.commit()
            message_id = message.id
        yield _sse(
            "done",
            {
                "session_id": session_id,
                "message_id": message_id,
                "needs_input": False,
                "provider": None,
                "route": "kitchen_recipe",
            },
        )
        return

    if route == "kitchen_recipe" or _is_direct_recipe_request(user_text, intent):
        recipe = intent.named_recipes[0] if intent.named_recipes else None
        if recipe is None:
            # 食材模糊查询:核心词命中配料(如「想吃虾」) → 发候选菜列表,由前端点击展开做法
            fuzzy_query = _extract_food_query(user_text)
            fuzzy_items, fuzzy_total = _recall_recipes_by_ingredient(fuzzy_query, context)
            if fuzzy_items:
                # 合成思考过程:把真实的规则执行步骤讲给用户(本地计算,不做人为延迟)
                fuzzy_thinking = (
                    f"【理解需求】从你的话里提取想吃的食材：「{fuzzy_query}」\n"
                    f"【模糊匹配】与 {len(context.recipes)} 道库内菜的配料双向匹配，命中 {fuzzy_total} 道，主料优先、临期加权\n"
                    "【标注】库存使用与过敏/忌口冲突只提示不过滤，决定权在你\n"
                )
                for chunk in fuzzy_thinking.splitlines():
                    if chunk:
                        yield _sse("thinking", {"delta": chunk + "\n"})
                lead_text = (
                    f"为你找到 {len(fuzzy_items)} 道含「{fuzzy_query}」的菜"
                    + (f"（共 {fuzzy_total} 道，先展示最相关的 {len(fuzzy_items)} 道）" if fuzzy_total > len(fuzzy_items) else "")
                    + "，点击菜名即可查看按当前人数换算的做法。"
                    "标红的含你的过敏原、标黄的撞上当前忌口或状态，仅供参考，仍可查看。"
                )
                yield _sse(
                    "candidates",
                    {"query": fuzzy_query, "total": fuzzy_total, "items": fuzzy_items},
                )
                yield _sse("text", {"delta": lead_text})
                with SessionLocal() as session:
                    message = AgentChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=lead_text,
                        thinking_text=fuzzy_thinking,
                        run_id=None,
                    )
                    session.add(message)
                    session.commit()
                    message_id = message.id
                yield _sse(
                    "done",
                    {
                        "session_id": session_id,
                        "message_id": message_id,
                        "needs_input": False,
                        "provider": None,
                        "route": "kitchen_recipe",
                        "search_queries": [fuzzy_query],
                    },
                )
                return
            dish_name = _dish_name_from_text(user_text)
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            async for kind, delta in _llm_stream_text(
                [
                    {"role": "system", "content": _generic_recipe_prompt(dish_name, context)},
                    *_recent_history_messages(session_id, current_user_message_id),
                    {"role": "user", "content": user_text},
                ]
            ):
                if kind == "thinking" and delta:
                    thinking_parts.append(delta)
                    yield _sse("thinking", {"delta": delta})
                elif kind == "text" and delta:
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
                    thinking_text="".join(thinking_parts) or None,
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
                "search_queries": [dish_name],
            })
            return
        if recipe is not None:
            diners = _extract_diners(user_text) or context.expected_diners
            conflict = _conflict_for(recipe, context)
            text_parts: list[str] = []
            thinking_parts: list[str] = []
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
                        *_recent_history_messages(session_id, current_user_message_id),
                        {"role": "user", "content": user_text},
                    ]
                ):
                    if kind == "thinking" and delta:
                        thinking_parts.append(delta)
                        yield _sse("thinking", {"delta": delta})
                    elif kind == "text" and delta:
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
                    thinking_text="".join(thinking_parts) or None,
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
                    "search_queries": [recipe.name],
                },
            )
            return



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


def delete_session(session_id: str) -> bool:
    """删除会话及其全部消息;会话不存在返回 False。"""
    with SessionLocal() as session:
        chat_session = session.get(AgentChatSession, session_id)
        if chat_session is None:
            return False
        session.query(AgentChatMessage).filter(
            AgentChatMessage.session_id == session_id
        ).delete(synchronize_session=False)
        session.delete(chat_session)
        session.commit()
        return True


def list_sessions(workspace_id: str, limit: int = 30) -> list[ChatSessionSummary]:
    """会话列表:按最近更新倒序,只回摘要不含消息体;空会话(无消息)不展示。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(AgentChatSession)
            .where(AgentChatSession.workspace_id == workspace_id)
            .order_by(AgentChatSession.updated_at.desc())
            .limit(limit * 2)
        ).all()
        summaries: list[ChatSessionSummary] = []
        for row in rows:
            has_message = session.scalar(
                select(AgentChatMessage.id).where(AgentChatMessage.session_id == row.id).limit(1)
            )
            if has_message is None:
                continue
            summaries.append(
                ChatSessionSummary(
                    session_id=row.id,
                    title=row.title,
                    updated_at=row.updated_at.isoformat(),
                )
            )
            if len(summaries) >= limit:
                break
        return summaries
