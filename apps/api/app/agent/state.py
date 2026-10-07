from typing import Any, TypedDict

# LangGraph 在运行时解析类型注解,这些引用必须是真实可导入的
# (经 app.services → app.schemas 的层级,不会与 app.agent 形成导入循环)
from app.schemas.agent import AgentRunView, PlanningConstraints, ToolTraceView
from app.services.context_loader import PlanningContext


class MealPlanningState(TypedDict, total=False):
    """配餐工作流状态图的状态载体。

    键值允许承载对象引用(PlanningContext/AgentRunView 等),节点间直接传递
    Python 对象,不做序列化——图只在进程内同步运行,不需要跨进程持久化。
    """

    # 作用域与输入
    workspace_id: str
    site_id: str
    meal_service_id: str
    request_text: str

    # 节点产物(对象引用)
    context: PlanningContext
    constraints: PlanningConstraints
    parse_trace: ToolTraceView
    parse_used_llm: bool
    candidate_recipes: list[Any]  # hard_filter 后保留的 RecipeContext 列表
    filtered_out: list[tuple[str, str]]
    key_names: dict[str, str]
    chosen: list[Any]  # 选定策略的主推菜谱(RecipeContext 列表)
    diners: int  # 本次用餐人数(constraints 覆盖或作用域默认)
    requirements: dict[str, Any]  # 按人数换算的食材需求(Decimal)
    menu_options: list[Any]  # build_all_options 产物(MenuOption 列表)

    # 汇总产物
    tool_trace: list[ToolTraceView]
    warnings: list[str]
    workspace_restrictions: list[str]
    selected_option: dict[str, Any] | None
    inventory_snapshot: list[dict[str, Any]]
    feedback_summary: dict[str, Any]
    approval_status: str
    plan: AgentRunView | None
    error: str | None

    # 运行时注入(非节点产物):LLM provider 与 SSE 直播回调
    provider: Any
    on_step: Any
    on_thinking: Any
