import re
from copy import deepcopy
from uuid import uuid4

from app.core.config import get_settings
from app.schemas.agent import (
    AgentRunView,
    MenuOption,
    PlanningConstraints,
    RunStatus,
    ToolTraceView,
)

_RUNS: dict[str, AgentRunView] = {}


def _extract_constraints(text: str) -> PlanningConstraints:
    diner_match = re.search(r"(\d+)\s*人", text)
    budget_match = re.search(r"预算\s*(\d+)\s*元", text)
    return PlanningConstraints(
        expected_diners=int(diner_match.group(1)) if diner_match else None,
        budget_limit_cents=int(budget_match.group(1)) * 100 if budget_match else None,
        dietary_style=[item for item in ["清淡" if "清淡" in text else None] if item],
        excluded_ingredients=["花生"] if "花生" in text else [],
        prioritize_expiring="临期" in text or "到期" in text,
        time_limit_minutes=90,
    )


def _trace(name: str, output: str, duration: int) -> ToolTraceView:
    return ToolTraceView(
        tool_name=name,
        status="success",
        duration_ms=duration,
        input_summary="已校验业务作用域",
        output_summary=output,
    )


def _options(diners: int, budget_cents: int | None) -> list[MenuOption]:
    factor = diners / 120
    base_costs = [83600, 78200, 89500]
    strategies = [
        ("expiring_first", "临期优先", {"expiring": 0.92, "cost": 0.72, "feedback": 0.76}),
        ("cost_first", "成本优先", {"expiring": 0.68, "cost": 0.94, "feedback": 0.71}),
        ("satisfaction_first", "满意度优先", {"expiring": 0.64, "cost": 0.66, "feedback": 0.93}),
    ]
    result: list[MenuOption] = []
    for index, (key, title, score) in enumerate(strategies):
        cost = round(base_costs[index] * factor)
        warnings = []
        if budget_cents and cost > budget_cents:
            warnings.append("预计成本超过当前预算，需调整方案")
        result.append(
            MenuOption(
                strategy=key,
                title=title,
                items=[
                    {"name": "番茄炒蛋", "servings": diners, "kcal_per_serving": 186},
                    {"name": "清炒时蔬", "servings": diners, "kcal_per_serving": 92},
                    {"name": "土豆烧鸡", "servings": diners, "kcal_per_serving": 328},
                ],
                estimated_cost_cents=cost,
                estimated_kcal_per_serving=606,
                score_breakdown=score,
                procurement_list=[
                    {"ingredient": "鸡蛋", "missing_quantity": f"{round(18 * factor, 1)}kg"},
                    {"ingredient": "鸡胸肉", "missing_quantity": f"{round(24 * factor, 1)}kg"},
                ],
                reasons=["命中清淡偏好", "已排除花生", "优先利用两天内到期的番茄"],
                warnings=warnings,
            )
        )
    return result


def create_demo_run(request_text: str) -> AgentRunView:
    settings = get_settings()
    constraints = _extract_constraints(request_text)
    diners = constraints.expected_diners or 120
    run = AgentRunView(
        id=str(uuid4()),
        status=RunStatus.WAITING_APPROVAL,
        constraints=constraints,
        tool_trace=[
            _trace("get_meal_service_context", f"午餐，预计 {diners} 人", 18),
            _trace("list_inventory", "4 项库存，发现 1 项临期", 24),
            _trace("get_feedback_summary", "平均分 4.1，主要标签：份量少", 16),
            _trace("search_recipe_candidates", "召回 20 道候选菜", 41),
            _trace("filter_hard_constraints", "过滤含花生菜品 2 道", 12),
            _trace("scale_recipe_quantities", f"已按 {diners} 人换算", 9),
            _trace("estimate_nutrition_and_cost", "已完成热量与成本估算", 15),
            _trace("build_procurement_list", "已生成采购缺口", 11),
        ],
        options=_options(diners, constraints.budget_limit_cents),
        warnings=["当前为规则基线骨架；配置云端模型后替换约束解析节点"],
        approval_status="waiting",
        provider=settings.llm_provider if settings.llm_api_key else None,
        model=settings.llm_model or None,
    )
    _RUNS[run.id] = run
    return run


def get_demo_run(run_id: str) -> AgentRunView | None:
    return _RUNS.get(run_id)


def revise_demo_run(
    run_id: str, expected_diners: int | None, budget_limit_cents: int | None
) -> AgentRunView | None:
    current = _RUNS.get(run_id)
    if current is None:
        return None
    revised = current.model_copy(deep=True)
    constraints = deepcopy(revised.constraints)
    if expected_diners is not None:
        constraints.expected_diners = expected_diners
    if budget_limit_cents is not None:
        constraints.budget_limit_cents = budget_limit_cents
    diners = constraints.expected_diners or 120
    revised.constraints = constraints
    revised.options = _options(diners, constraints.budget_limit_cents)
    revised.tool_trace.extend(
        [
            _trace("scale_recipe_quantities", f"What-if：重新按 {diners} 人换算", 8),
            _trace("build_procurement_list", "What-if：已更新采购缺口", 10),
        ]
    )
    _RUNS[run_id] = revised
    return revised
