from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PARSING = "PARSING"
    RUNNING_TOOLS = "RUNNING_TOOLS"
    BUILDING_OPTIONS = "BUILDING_OPTIONS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PUBLISHED = "PUBLISHED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class PlanningConstraints(BaseModel):
    expected_diners: int | None = Field(default=None, gt=0)
    budget_limit_cents: int | None = Field(default=None, gt=0)
    dietary_style: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    preferred_dishes: list[str] = Field(default_factory=list)
    prioritize_expiring: bool = False
    time_limit_minutes: int | None = Field(default=None, gt=0)


class ToolTraceView(BaseModel):
    tool_name: str
    status: str
    duration_ms: int = 0
    input_summary: str = ""
    output_summary: str = ""
    error_code: str | None = None


class MenuOption(BaseModel):
    strategy: str
    title: str
    items: list[dict] = Field(default_factory=list)
    estimated_cost_cents: int = 0
    estimated_kcal_per_serving: int | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    procurement_list: list[dict] = Field(default_factory=list)
    pantry_notes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CreateAgentRunRequest(BaseModel):
    workspace_id: str
    site_id: str
    meal_service_id: str
    request_text: str = Field(min_length=2, max_length=1000)


class ReviseAgentRunRequest(BaseModel):
    expected_diners: int | None = Field(default=None, gt=0)
    budget_limit_cents: int | None = Field(default=None, gt=0)
    replacement_request: str | None = Field(default=None, max_length=300)


class AgentRunView(BaseModel):
    id: str
    status: RunStatus
    constraints: PlanningConstraints
    tool_trace: list[ToolTraceView]
    options: list[MenuOption]
    warnings: list[str] = Field(default_factory=list)
    # 家庭档案预置的用餐限制（如 过敏原：花生米），硬过滤来源与本次输入无关
    workspace_restrictions: list[str] = Field(default_factory=list)
    approval_status: str = "not_requested"
    provider: str | None = None
    model: str | None = None
