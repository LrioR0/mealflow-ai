"""受控的对话工具循环。

这里的模型只负责决定是否读取只读家庭数据、何时停止并组织回答；配餐过滤、
评分、换算和所有写操作仍由确定性业务工作流负责。
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.llm.provider import LLMProvider
from app.schemas.agent import ToolTraceView
from app.services.context_loader import PlanningContext, load_planning_context


_SYSTEM_PROMPT = """你是 MealFlow 的家庭厨房对话 Agent。
你可以通过工具读取家庭成员限制、冰箱库存、本地菜谱和历史偏好，再基于工具结果回答。
只有信息确实需要时才调用工具；绝不编造库存、家庭限制、历史偏好或菜谱命中。
工具全部只读：你不能修改库存、创建采购单、发布餐单或绕过人工确认。
需要正式配餐时，先向用户清晰总结你已知的人数、时段、偏好和限制，并请用户确认生成正式餐单。
回答使用简洁自然的简体中文。"""


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_member_constraints",
            "description": "读取当前用餐成员的过敏、忌口和特殊状态。涉及能不能吃、安排一餐或推荐菜时使用。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_summary",
            "description": "读取冰箱中的可用食材和临期食材。用户询问库存、根据现有食材做菜时使用。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_recipes",
            "description": "在本地菜谱库中按菜名、食材或口味检索菜谱摘要。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "菜名、食材或口味关键词"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_preference_summary",
            "description": "读取已记录的菜品评分和偏好摘要。需要根据家庭历史偏好推荐时使用。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


@dataclass
class ConversationTurn:
    text: str
    traces: list[ToolTraceView] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


def _load_context(workspace_id: str, site_id: str, meal_service_id: str) -> PlanningContext:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        return load_planning_context(session, workspace_id, site_id, meal_service_id)


def _restrict_constraints(context: PlanningContext, diner_ids: list[str] | None) -> list[Any]:
    if not diner_ids:
        return context.member_constraints
    selected = set(diner_ids)
    return [item for item in context.member_constraints if not item.user_id or item.user_id in selected]


def _tool_result(
    tool_name: str,
    arguments: dict[str, Any],
    context: PlanningContext,
    diner_ids: list[str] | None,
) -> tuple[dict[str, Any], str]:
    """执行固定白名单工具；返回机器结果和可展示的摘要。"""
    if tool_name == "get_member_constraints":
        rows = _restrict_constraints(context, diner_ids)
        result = {"constraints": [row.summary for row in rows], "count": len(rows)}
        return result, "未发现生效限制" if not rows else "；".join(result["constraints"])

    if tool_name == "get_inventory_summary":
        today = date.today()
        items = [
            {"name": line.name, "quantity": str(line.quantity), "unit": line.unit, "expiring": line.key in context.expiring_keys(today)}
            for line in context.inventory
        ]
        result = {"items": items[:20], "total": len(items), "expiring": [item["name"] for item in items if item["expiring"]]}
        detail = "、".join(result["expiring"]) or "无临期食材"
        return result, f"{len(items)} 项可用库存，临期：{detail}"

    if tool_name == "search_recipes":
        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            raise ValueError("缺少 query")
        matches = []
        for recipe in context.recipes:
            haystack = " ".join(
                [recipe.name, *recipe.tags, *recipe.taste_tags, *(line.name for line in recipe.ingredients)]
            ).lower()
            if query in haystack:
                matches.append(
                    {
                        "id": recipe.id,
                        "name": recipe.name,
                        "duration_minutes": recipe.duration_minutes,
                        "tags": recipe.tags[:4],
                        "ingredients": [line.name for line in recipe.ingredients[:8]],
                    }
                )
        result = {"query": query, "recipes": matches[:8], "total": len(matches)}
        return result, f"“{query}”命中 {len(matches)} 道菜谱"

    if tool_name == "get_preference_summary":
        rows = [
            {"dish": name, "rating": stats.avg_rating, "count": stats.sample_count, "tags": stats.top_tags}
            for name, stats in context.dish_feedback.items()
        ]
        result = {"preferences": rows[:10], "total": len(rows)}
        return result, "暂无历史偏好记录" if not rows else f"读取到 {len(rows)} 条历史偏好"

    raise ValueError(f"不允许调用工具：{tool_name}")


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    """OpenAI-compatible chat_completions 返回 message.tool_calls。"""
    calls = response.get("tool_calls") or []
    return [call for call in calls if isinstance(call, dict) and isinstance(call.get("function"), dict)]


async def run_conversation_agent(
    *,
    provider: LLMProvider | None,
    workspace_id: str,
    site_id: str,
    meal_service_id: str,
    diner_ids: list[str] | None,
    user_text: str,
    history: list[dict[str, str]],
    max_steps: int,
    on_tool: Callable[[ToolTraceView], None] | None = None,
) -> ConversationTurn | None:
    """运行有限步骤的只读工具循环。

    ``None`` 表示 Provider 不可用或协议不兼容，调用方应走现有确定性降级分支。
    """
    if provider is None:
        return None

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_text},
    ]
    context: PlanningContext | None = None
    traces: list[ToolTraceView] = []
    results: list[dict[str, Any]] = []
    steps = max(1, min(max_steps, 6))
    tool_actions = 0

    for _ in range(steps):
        try:
            response = await provider.chat_with_tools(messages=messages, tools=TOOL_DEFINITIONS)
        except Exception:
            return None
        calls = _extract_tool_calls(response)
        if not calls:
            text = str(response.get("content") or "").strip()
            return ConversationTurn(text=text, traces=traces, tool_results=results) if text else None

        # 同一轮可以并行请求几个相互独立的只读工具；每个都必须返回结果。
        # 保留 reasoning_content 是 DeepSeek/GLM 等思考模型继续 tool loop 的必要协议字段。
        assistant_message = {
            "role": response.get("role") or "assistant",
            "content": response.get("content") or "",
            "tool_calls": calls,
        }
        if response.get("reasoning_content"):
            assistant_message["reasoning_content"] = response["reasoning_content"]
        messages.append(assistant_message)

        for call in calls:
            function = call["function"]
            tool_name = str(function.get("name", ""))
            if tool_actions >= steps:
                result = {"error": "本轮只读工具调用已达上限，请根据已有结果作答"}
                trace = ToolTraceView(
                    tool_name=tool_name or "unknown",
                    status="error",
                    input_summary="已达工具调用上限",
                    output_summary=result["error"],
                    error_code="tool_limit_reached",
                )
                traces.append(trace)
                results.append({"tool_name": trace.tool_name, "status": trace.status, "summary": trace.output_summary})
                if on_tool:
                    on_tool(trace)
                messages.append(
                    {"role": "tool", "tool_call_id": str(call.get("id") or tool_name), "content": json.dumps(result, ensure_ascii=False)}
                )
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("工具参数必须是对象")
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = {}
                result: dict[str, Any] = {"error": f"参数无效：{exc}"}
                summary = result["error"]
                trace = ToolTraceView(tool_name=tool_name or "unknown", status="error", input_summary="参数解析", output_summary=summary, error_code="invalid_arguments")
            else:
                started = time.perf_counter()
                try:
                    if context is None:
                        context = _load_context(workspace_id, site_id, meal_service_id)
                    result, summary = _tool_result(tool_name, arguments, context, diner_ids)
                    trace = ToolTraceView(
                        tool_name=tool_name,
                        status="success",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        input_summary=json.dumps(arguments, ensure_ascii=False),
                        output_summary=summary,
                    )
                except Exception as exc:
                    result = {"error": f"工具执行失败：{type(exc).__name__}"}
                    trace = ToolTraceView(
                        tool_name=tool_name or "unknown",
                        status="error",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        input_summary=json.dumps(arguments, ensure_ascii=False),
                        output_summary=result["error"],
                        error_code="tool_execution_failed",
                    )
            traces.append(trace)
            tool_actions += 1
            results.append({"tool_name": trace.tool_name, "status": trace.status, "summary": trace.output_summary})
            if on_tool:
                on_tool(trace)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or tool_name),
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        if tool_actions >= steps:
            try:
                text = await provider.chat(
                    messages=[
                        *messages,
                        {
                            "role": "system",
                            "content": "本轮工具调用额度已用尽。请只依据已有工具结果立即给出最终回答，不要继续请求工具。",
                        },
                    ]
                )
                if text.strip():
                    return ConversationTurn(text=text.strip(), traces=traces, tool_results=results)
            except Exception:
                pass
            break

    # 上限不是失败：让用户知道没有继续展开，避免循环无限消耗。
    return ConversationTurn(
        text="我已经完成了本轮可用信息查询。为了避免重复查询，请告诉我你想优先决定哪一点。",
        traces=traces,
        tool_results=results,
    )
