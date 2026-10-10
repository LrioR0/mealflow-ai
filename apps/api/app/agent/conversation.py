"""受控、可观测的对话工具循环。"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.exc import OperationalError

from app.llm.provider import LLMProvider
from app.schemas.agent import ToolTraceView
from app.services.context_loader import PlanningContext, RecipeContext, load_planning_context

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是 MealFlow 的家庭厨房对话 Agent。你可以读取家庭限制、冰箱、本地菜谱和历史偏好。只能使用工具已返回的事实，绝不编造库存、限制或菜谱。
如果用户肯定上一轮你提出的“帮你查某道菜/菜谱”建议，必须从会话上下文提取菜名并调用菜谱工具，不能重复提问。
用户明确要求多道菜、几菜一汤、按冰箱配餐时，先读取必要的库存和限制，再调用 recommend_menu；它已包含逐菜可用性检查，不要再为同一需求反复检索。缺少非辅料主料不是拒答理由：仍给出完整做法，并把缺项作为可选采购建议；不要要求用户先补货。常备料默认可用，但过敏或忌口不能绕过。你不能写库存、创建采购单或发布餐单。使用简洁自然的简体中文。"""

TOOL_META = {
    "get_member_constraints": ("检查用餐限制", "当前家庭成员的饮食限制"),
    "get_inventory_summary": ("读取冰箱库存", "可用食材与临期食材"),
    "search_recipes": ("检索本地菜谱", "查询“{query}”"),
    "get_recipe_detail": ("读取菜谱做法", "查看“{recipe}”的食材和步骤"),
    "check_recipe_availability": ("核对食材可用性", "核对“{recipe}”的库存与缺项"),
    "get_preference_summary": ("读取家庭偏好", "历史评分与偏好"),
    "recommend_menu": ("生成本餐建议", "按库存与限制推荐 {dish_count} 道菜"),
}

def _tool(name: str, description: str, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}

TOOL_DEFINITIONS = [
    _tool("get_member_constraints", "读取当前用餐成员的过敏、忌口和特殊状态。"),
    _tool("get_inventory_summary", "读取冰箱中的可用和临期食材。"),
    _tool("search_recipes", "按菜名、食材或口味检索本地菜谱。", {"query": {"type": "string"}}, ["query"]),
    _tool("get_recipe_detail", "按菜谱 ID 或名称读取完整食材、步骤和份量。", {"recipe": {"type": "string"}}, ["recipe"]),
    _tool("check_recipe_availability", "核对一道菜的主料库存、缺少主料、常备辅料和限制。", {"recipe": {"type": "string"}}, ["recipe"]),
    _tool("get_preference_summary", "读取已记录的菜品评分和偏好摘要。"),
    _tool("recommend_menu", "根据库存、限制和偏好生成多菜餐食候选；用户提出几菜一汤、主食或多人配餐时使用。", {"dish_count": {"type": "integer", "minimum": 1, "maximum": 6}, "need_soup": {"type": "boolean"}, "staple": {"type": "string"}, "style": {"type": "string"}, "preferred_ingredients": {"type": "array", "items": {"type": "string"}}}),
]

@dataclass
class ConversationTurn:
    text: str
    traces: list[ToolTraceView] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    procurement_suggestions: list[dict[str, Any]] = field(default_factory=list)
    menu_recommendation: dict[str, Any] | None = None


def _suggestion_key(item: dict[str, Any]) -> str:
    """同一菜谱的同一缺项只向用户展示一次。"""
    source = str(item.get("source_id") or item.get("recipe_id") or "")
    ingredient = str(item.get("ingredient_key") or item.get("ingredient") or "")
    return f"{source}:{ingredient}"

def _load_context(workspace_id: str, site_id: str, meal_service_id: str) -> PlanningContext:
    from app.db.session import SessionLocal
    with SessionLocal() as session:
        return load_planning_context(session, workspace_id, site_id, meal_service_id)

def _recipe(context: PlanningContext, value: str) -> RecipeContext:
    value = value.strip().lower()
    for item in context.recipes:
        if item.id == value or item.name.lower() == value or value in item.name.lower(): return item
    raise ValueError("未找到对应本地菜谱")

def _availability(recipe: RecipeContext, context: PlanningContext, diner_ids: list[str] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    restricted = {r.ingredient_key for r in context.member_constraints if r.ingredient_key and (not diner_ids or not r.user_id or r.user_id in diner_ids)}
    groups: dict[str, list[dict[str, Any]]] = {x: [] for x in ("available_main_ingredients", "missing_main_ingredients", "pantry_staples", "optional_ingredients", "restricted_ingredients")}
    suggestions: list[dict[str, Any]] = []
    for line in recipe.ingredients:
        row = {"key": line.key, "name": line.name, "quantity": str(line.quantity), "unit": line.unit}
        if line.key in restricted: groups["restricted_ingredients"].append(row)
        elif line.optional: groups["optional_ingredients"].append(row)
        elif line.key in context.pantry_keys: groups["pantry_staples"].append(row)
        elif context.available_for(line.key) > 0: groups["available_main_ingredients"].append(row)
        else:
            groups["missing_main_ingredients"].append(row)
            suggestions.append({"ingredient": line.name, "quantity": str(line.quantity), "unit": line.unit, "recipe_id": recipe.id, "recipe_name": recipe.name, "source_id": f"chat:{recipe.id}", "reason": f"制作{recipe.name}缺少的主料"})
    return {"recipe_id": recipe.id, "recipe_name": recipe.name, **groups, "can_cook_without_purchase": not groups["missing_main_ingredients"] and not groups["restricted_ingredients"]}, suggestions

def _recommend_menu(args: dict[str, Any], context: PlanningContext, diner_ids: list[str] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """确定性候选排序；模型只决定何时请求和如何解释，不能绕过限制。"""
    dish_count = max(1, min(int(args.get("dish_count") or 3), 6))
    want_soup = bool(args.get("need_soup")); style = str(args.get("style") or "").strip().lower()
    preferred = {str(item).lower() for item in args.get("preferred_ingredients") or [] if str(item).strip()}
    rows: list[tuple[RecipeContext, dict[str, Any], list[dict[str, Any]]]] = []
    for recipe in context.recipes:
        availability, suggestions = _availability(recipe, context, diner_ids)
        rows.append((recipe, availability, suggestions))
    def rank(item: tuple[RecipeContext, dict[str, Any], list[dict[str, Any]]]) -> tuple[int, int, int, str]:
        recipe, availability, _ = item
        preferred_hit = sum(ingredient.name.lower() in preferred for ingredient in recipe.ingredients)
        return (bool(availability["restricted_ingredients"]), len(availability["missing_main_ingredients"]), -preferred_hit, recipe.name)
    rows.sort(key=rank)
    if want_soup:
        soups = [row for row in rows if "汤" in row[0].name]
        nonsoups = [row for row in rows if row not in soups]
        chosen = (soups[:1] + nonsoups)[:dish_count]
    else:
        chosen = rows[:dish_count]
    menu_items, suggestions = [], []
    for recipe, availability, missing in chosen:
        if availability["restricted_ingredients"]: state = "restricted"
        elif availability["missing_main_ingredients"]: state = "purchase_optional"
        else: state = "ready"
        menu_items.append({"recipe_id": recipe.id, "name": recipe.name, "duration_minutes": recipe.duration_minutes, "state": state, "used_inventory": [x["name"] for x in availability["available_main_ingredients"]], "pantry_staples": [x["name"] for x in availability["pantry_staples"]], "missing_main_ingredients": [x["name"] for x in availability["missing_main_ingredients"]], "restricted_ingredients": [x["name"] for x in availability["restricted_ingredients"]]})
        suggestions.extend(missing)
    unique_suggestions = {f"{x['source_id']}:{x['ingredient']}": x for x in suggestions}
    result = {"dish_count": dish_count, "staple": str(args.get("staple") or ""), "style": style, "items": menu_items, "ready_count": sum(x["state"] == "ready" for x in menu_items), "purchase_optional_count": sum(x["state"] == "purchase_optional" for x in menu_items), "restricted_count": sum(x["state"] == "restricted" for x in menu_items), "estimated_parallel_minutes": max((x["duration_minutes"] for x in menu_items), default=0), "reason": "优先使用现有库存并避开已知限制"}
    return result, list(unique_suggestions.values())

def _run_tool(name: str, args: dict[str, Any], context: PlanningContext, diner_ids: list[str] | None) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    if name == "get_member_constraints":
        rows = [r.summary for r in context.member_constraints if not diner_ids or not r.user_id or r.user_id in diner_ids]
        return {"constraints": rows, "count": len(rows)}, "未发现生效限制" if not rows else "；".join(rows), []
    if name == "get_inventory_summary":
        today = date.today(); items = [{"name": x.name, "quantity": str(x.quantity), "unit": x.unit, "expiring": x.key in context.expiring_keys(today)} for x in context.inventory]
        return {"items": items[:20], "total": len(items), "expiring": [x["name"] for x in items if x["expiring"]]}, f"{len(items)} 项可用库存", []
    if name == "search_recipes":
        query = str(args.get("query", "")).strip().lower()
        if not query: raise ValueError("缺少 query")
        matches = [r for r in context.recipes if query in " ".join([r.name, *r.tags, *r.taste_tags, *(x.name for x in r.ingredients)]).lower()]
        return {"query": query, "recipes": [{"id": r.id, "name": r.name, "duration_minutes": r.duration_minutes, "ingredients": [x.name for x in r.ingredients]} for r in matches[:8]], "total": len(matches)}, f"“{query}”命中 {len(matches)} 道菜谱", []
    if name in {"get_recipe_detail", "check_recipe_availability"}:
        recipe = _recipe(context, str(args.get("recipe", ""))); availability, suggestions = _availability(recipe, context, diner_ids)
        if name == "check_recipe_availability": return availability, f"{recipe.name}：{len(availability['missing_main_ingredients'])} 项非辅料缺项，{len(availability['pantry_staples'])} 项常备料", suggestions
        result = {"id": recipe.id, "name": recipe.name, "servings": recipe.servings, "duration_minutes": recipe.duration_minutes, "ingredients": [{"key": x.key, "name": x.name, "quantity": str(x.quantity), "unit": x.unit, "optional": x.optional, "is_pantry_staple": x.key in context.pantry_keys} for x in recipe.ingredients], "steps": recipe.steps, "availability": availability}
        return result, f"已读取《{recipe.name}》的食材与 {len(recipe.steps)} 个步骤", suggestions
    if name == "get_preference_summary":
        rows = [{"dish": n, "rating": v.avg_rating, "count": v.sample_count, "tags": v.top_tags} for n, v in context.dish_feedback.items()]
        return {"preferences": rows[:10], "total": len(rows)}, "暂无历史偏好记录" if not rows else f"读取到 {len(rows)} 条历史偏好", []
    if name == "recommend_menu":
        result, suggestions = _recommend_menu(args, context, diner_ids)
        return result, f"已生成 {len(result['items'])} 道菜建议：{result['ready_count']} 道可直接做，{result['purchase_optional_count']} 道可选采购", suggestions
    raise ValueError(f"不允许调用工具：{name}")

def _calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in response.get("tool_calls") or [] if isinstance(x, dict) and isinstance(x.get("function"), dict)]

def _trace(name: str, status: str, args: dict[str, Any], **extra: Any) -> ToolTraceView:
    label, template = TOOL_META.get(name, ("读取家庭数据", "执行查询"))
    try:
        summary = template.format(**args) if status == "running" else label
    except KeyError:
        summary = label
    return ToolTraceView(tool_name=name, status=status, input_summary=summary, **extra)

def _tool_error(exc: Exception) -> tuple[str, str]:
    """前端拿到可行动信息，服务端日志保留原始堆栈。"""
    if isinstance(exc, OperationalError):
        return ("数据库暂不可用或结构未升级；请执行数据库迁移后重启服务", "database_operational_error")
    return (f"工具执行失败：{type(exc).__name__}", "tool_execution_failed")

async def stream_conversation_agent(*, provider: LLMProvider | None, workspace_id: str, site_id: str, meal_service_id: str, diner_ids: list[str] | None, user_text: str, history: list[dict[str, str]], max_steps: int) -> AsyncIterator[dict[str, Any]]:
    if provider is None: yield {"type": "fallback"}; return
    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}, *history, {"role": "user", "content": user_text}]
    context: PlanningContext | None = None; traces: list[ToolTraceView] = []; results: list[dict[str, Any]] = []; suggestions: dict[str, dict[str, Any]] = {}; menu_recommendation: dict[str, Any] | None = None
    limit = max(1, min(max_steps, 8)); actions = 0
    # 读取家庭上下文与深入菜谱查询各自有预算，避免重复读库存挤掉菜单细化。
    context_names = {"get_member_constraints", "get_inventory_summary", "get_preference_summary"}
    context_budget = min(3, limit); recipe_budget = limit - context_budget
    context_actions = 0; recipe_actions = 0; tool_cache: dict[str, tuple[dict[str, Any], str, list[dict[str, Any]]]] = {}
    decision_rounds = 0
    while True:
        decision_rounds += 1
        if decision_rounds > limit + 1:
            yield {"type": "final", "turn": ConversationTurn("我已复用本轮已读取的信息完成判断。请告诉我想优先调整哪一道菜。", traces, results, list(suggestions.values()), menu_recommendation)}
            return
        yield {"type": "status", "step": "agent_decide", "label": "判断下一步", "state": "running"}
        try: response = await provider.chat_with_tools(messages=messages, tools=TOOL_DEFINITIONS)
        except Exception: yield {"type": "fallback"}; return
        yield {"type": "status", "step": "agent_decide", "label": "判断下一步", "state": "done", "detail": "已获得下一步决策"}
        calls = _calls(response)
        if not calls:
            text = str(response.get("content") or "").strip()
            yield {"type": "final", "turn": ConversationTurn(text, traces, results, list(suggestions.values()), menu_recommendation)} if text else {"type": "fallback"}; return
        assistant = {"role": response.get("role") or "assistant", "content": response.get("content") or "", "tool_calls": calls}
        if response.get("reasoning_content"): assistant["reasoning_content"] = response["reasoning_content"]
        messages.append(assistant)
        for call in calls:
            fn = call["function"]; name = str(fn.get("name") or "unknown")
            try: args = json.loads(fn.get("arguments") or "{}"); assert isinstance(args, dict)
            except Exception: args = {}
            fingerprint = f"{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            if fingerprint in tool_cache:
                result, summary, new = tool_cache[fingerprint]
                done = _trace(name, "success", args, duration_ms=0, output_summary=f"已复用本轮结果：{summary}")
            elif actions >= limit or (name in context_names and context_actions >= context_budget) or (name not in context_names and recipe_actions >= recipe_budget):
                budget_kind = "上下文读取" if name in context_names else "菜谱深入查询"
                result = {"error": f"{budget_kind}额度已用尽，请依据已有结果作答"}; done = _trace(name, "error", args, output_summary=result["error"], error_code="tool_limit_reached")
            else:
                yield {"type": "tool", "trace": _trace(name, "running", args, output_summary="正在读取")}
                started = time.perf_counter(); actions += 1
                if name in context_names: context_actions += 1
                else: recipe_actions += 1
                try:
                    if context is None: context = _load_context(workspace_id, site_id, meal_service_id)
                    result, summary, new = _run_tool(name, args, context, diner_ids)
                    for item in new:
                        suggestions.setdefault(_suggestion_key(item), item)
                    tool_cache[fingerprint] = (result, summary, new)
                    if name == "recommend_menu": menu_recommendation = result
                    done = _trace(name, "success", args, duration_ms=max(1, round((time.perf_counter()-started)*1000)), output_summary=summary)
                except Exception as exc:
                    logger.exception("对话工具执行失败：%s", name)
                    message, error_code = _tool_error(exc)
                    result = {"error": message}; done = _trace(name, "error", args, duration_ms=max(1, round((time.perf_counter()-started)*1000)), output_summary=message, error_code=error_code)
            traces.append(done); results.append({"tool_name": name, "status": done.status, "summary": done.output_summary}); yield {"type": "tool", "trace": done}
            messages.append({"role": "tool", "tool_call_id": str(call.get("id") or name), "content": json.dumps(result, ensure_ascii=False)})
        if actions >= limit or (context_actions >= context_budget and recipe_actions >= recipe_budget):
            try:
                text = (await provider.chat(messages=[*messages, {"role": "system", "content": "工具额度已用尽。请立即依据已有结果作答，不得继续调用工具。"}])).strip()
                if text: yield {"type": "final", "turn": ConversationTurn(text, traces, results, list(suggestions.values()), menu_recommendation)}; return
            except Exception: pass
            yield {"type": "final", "turn": ConversationTurn("我已完成本轮查询。为避免重复查询，请告诉我你想优先决定哪一点。", traces, results, list(suggestions.values()), menu_recommendation)}; return

async def run_conversation_agent(**kwargs: Any) -> ConversationTurn | None:
    callback: Callable[[ToolTraceView], None] | None = kwargs.pop("on_tool", None)
    async for event in stream_conversation_agent(**kwargs):
        if event["type"] == "tool" and event["trace"].status != "running" and callback: callback(event["trace"])
        if event["type"] == "final": return event["turn"]
        if event["type"] == "fallback": return None
    return None
