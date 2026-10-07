"""家庭配餐 Agent 的 LangGraph 状态图。

编排层:把 agent_service._plan 里的顺序工具调用拆成图节点,业务核心
(planning.py / context_loader.py)以纯函数形式被节点调用,一行不改。
节点间通过 MealPlanningState 传递 Python 对象引用,不做序列化。
"""

import time
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.state import MealPlanningState
from app.schemas.agent import ToolTraceView
from app.services import planning
from app.services.context_loader import PlanningContext


def _timed_trace(
    name: str, input_summary: str, produce, on_step=None
) -> tuple[ToolTraceView, Any]:
    """与 agent_service._timed_tool 同款:计时 + 开始/结束直播 + 拆 (display, payload)。"""
    if on_step:
        on_step("running", name, input_summary)
    started = time.perf_counter()
    result = produce()
    duration_ms = round((time.perf_counter() - started) * 1000)
    if isinstance(result, tuple) and len(result) == 2:
        display, payload = result
    else:
        display, payload = result, None
    if on_step:
        on_step("done", name, str(display))
    return (
        ToolTraceView(
            tool_name=name,
            status="success",
            duration_ms=duration_ms,
            input_summary=input_summary,
            output_summary=str(display),
        ),
        payload,
    )


async def parse_request(state: MealPlanningState) -> MealPlanningState:
    """约束解析:LLM 优先,失败/未配置降级规则基线(复用 agent_service 现成实现)。"""
    from app.services import agent_service  # 进程内延迟导入,避免模块循环

    on_step = state.get("on_step")
    on_thinking = state.get("on_thinking")
    if on_step:
        on_step("running", "parse_request", "解析人数、预算、点名菜品与忌口")
    constraints, parse_trace, used_llm = await agent_service._parse_constraints_with_llm(
        state["provider"],
        state["request_text"],
        state["context"],
        on_thinking=on_thinking,
    )
    if on_step:
        on_step("done", "parse_request", parse_trace.output_summary)
    return {
        **state,
        "constraints": constraints,
        "parse_trace": parse_trace,
        "parse_used_llm": used_llm,
    }


def load_context(state: MealPlanningState) -> MealPlanningState:
    """作用域校验 + 上下文快照:四条真实 trace 与旧行为一致。"""
    context: PlanningContext = state["context"]
    on_step = state.get("on_step")
    traces = [state["parse_trace"]]

    def _scope():
        diners = state["constraints"].expected_diners or context.expected_diners
        return (
            f"{context.workspace_name}·{context.site_name} "
            f"{context.service_date} {context.meal_service_name} 预计 {diners} 人",
            diners,
        )

    trace, diners = _timed_trace(
        "get_meal_service_context", "已校验业务作用域", _scope, on_step
    )
    traces = [*traces, trace]

    def _inventory_summary():
        expiring = context.expiring_keys(date.today())
        expiring_names = "、".join(
            line.name for line in context.inventory if line.key in expiring
        )
        return f"{len(context.inventory)} 项库存，临期 {len(expiring)} 项（{expiring_names}）"

    trace, _ = _timed_trace("list_inventory", "读取可用库存", _inventory_summary, on_step)
    traces = [*traces, trace]

    def _constraints_summary():
        if not context.member_constraints:
            return "全家当前没有生效的忌口或特殊事件"
        return "；".join(constraint.summary for constraint in context.member_constraints)

    trace, _ = _timed_trace(
        "get_member_constraints", "检查用餐限制", _constraints_summary, on_step
    )
    traces = [*traces, trace]

    trace, _ = _timed_trace(
        "search_recipe_candidates",
        "全量召回菜谱",
        lambda: f"召回 {len(context.recipes)} 道候选菜",
        on_step,
    )
    traces = [*traces, trace]

    return {**state, "diners": diners, "tool_trace": traces}


def build_options(state: MealPlanningState) -> MealPlanningState:
    """核心计算:硬约束过滤 → 多策略评分 → 方案生成 → 用量换算 → 缺口计算。

    与 agent_service._plan 的顺序逐行对应,业务函数全部来自 planning.py。
    """
    from app.services.agent_service import _restriction_chips  # 延迟导入避免循环

    context: PlanningContext = state["context"]
    constraints = state["constraints"]
    on_step = state.get("on_step")
    diners = state["diners"]
    traces = state["tool_trace"]

    key_names = planning.build_key_names(context)
    workspace_restrictions = _restriction_chips(context, key_names)

    def _hard_filter():
        kept, filtered_out = planning.hard_filter(
            context.recipes, context.excluded_keys, key_names, context.restriction_types
        )
        detail = "；".join(f"{name}（{reason}）" for name, reason in filtered_out) or "无"
        return f"保留 {len(kept)} 道，过滤 {len(filtered_out)} 道：{detail}", (kept, filtered_out)

    trace, (kept, filtered_out) = _timed_trace(
        "filter_hard_constraints",
        f"家庭档案限制：{'、'.join(workspace_restrictions) or '无'}",
        _hard_filter,
        on_step,
    )
    traces = [*traces, trace]

    expiring_keys = context.expiring_keys(context.service_date)

    def _score_and_build():
        scored = planning.score_candidates(kept, context, constraints, expiring_keys)
        options = planning.build_all_options(
            scored, context, constraints, filtered_out, key_names
        )
        summary = "、".join(
            f"{option.title}（{option.score_breakdown['total']}分）" for option in options
        )
        return f"三方案生成：{summary}", options

    trace, options = _timed_trace(
        "score_menu_options", f"候选 {len(kept)} 道，三策略加权", _score_and_build, on_step
    )
    traces = [*traces, trace]

    expiring_first = next(option for option in options if option.strategy == "expiring_first")
    chosen_names = {item["name"] for item in expiring_first.items}
    chosen_recipes = [recipe for recipe in kept if recipe.name in chosen_names]

    def _scale():
        requirements = planning.compute_requirements(chosen_recipes, diners)
        return (
            f"按 {diners} 人换算 {len(chosen_recipes)} 道菜共 {len(requirements)} 项食材用量",
            requirements,
        )

    trace, requirements = _timed_trace(
        "scale_recipe_quantities", f"基准份数 → {diners} 人", _scale, on_step
    )
    traces = [*traces, trace]

    def _estimate() -> str:
        total_cost, total_kcal = planning.estimate_totals(chosen_recipes, diners)
        return (
            f"按“{expiring_first.title}”估算：人均约 {total_kcal} kcal，"
            f"总成本约 {total_cost / 100:.0f} 元"
        )

    trace, _ = _timed_trace("estimate_nutrition_and_cost", "热量与成本估算", _estimate, on_step)
    traces = [*traces, trace]

    def _procurement() -> str:
        lines = planning.procurement_lines(requirements, context, key_names)
        detail = "、".join(
            f"{line['ingredient']} 缺 {line['missing_quantity']}" for line in lines[:5]
        )
        return f"{len(lines)} 项采购缺口：{detail}"

    trace, _ = _timed_trace("build_procurement_list", "比对库存计算缺口", _procurement, on_step)
    traces = [*traces, trace]

    warnings: list[str] = []
    if state["parse_trace"].status == "skipped":
        warnings.append("未配置云端模型（LLM_API_KEY 为空），约束解析由规则基线完成")
    elif state["parse_trace"].status == "fallback":
        warnings.append("云端模型解析失败，约束解析已降级规则基线（详见工具轨迹 parse_request）")

    return {
        **state,
        "menu_options": options,
        "chosen": chosen_recipes,
        "requirements": requirements,
        "tool_trace": traces,
        "warnings": warnings,
        "workspace_restrictions": workspace_restrictions,
    }


def wait_for_human(state: MealPlanningState) -> MealPlanningState:
    """方案产出后等待人工确认(审批动作在 HTTP 层完成,图在此交付终态)。

    预留:引入 checkpointer 后可改为 langgraph.types.interrupt 实现进程内挂起/恢复。
    """
    return {**state, "approval_status": "waiting"}


def build_meal_planning_graph():
    graph = StateGraph(MealPlanningState)
    graph.add_node("parse_request", parse_request)
    graph.add_node("load_context", load_context)
    graph.add_node("build_options", build_options)
    graph.add_node("wait_for_human", wait_for_human)
    graph.add_edge(START, "parse_request")
    graph.add_edge("parse_request", "load_context")
    graph.add_edge("load_context", "build_options")
    graph.add_edge("build_options", "wait_for_human")
    graph.add_edge("wait_for_human", END)
    return graph.compile()
