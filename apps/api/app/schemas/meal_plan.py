"""菜单计划契约（docs/api.md：POST /meal-plans、POST /meal-plans/{id}/publish）。

发布接口要求 Agent run、选中方案和管理员确认状态，并使用 Idempotency-Key。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class MealPlanCreate(BaseModel):
    agent_run_id: str
    strategy: str = Field(min_length=1, max_length=40)


class MealPlanView(BaseModel):
    id: str
    workspace_id: str
    meal_service_id: str
    agent_run_id: str
    strategy: str
    status: str
    items: list[dict] = Field(default_factory=list)
    procurement_list: list[dict] = Field(default_factory=list)
    estimated_cost_cents: int = 0
    constraints_snapshot: dict = Field(default_factory=dict)
    published_at: datetime | None = None
