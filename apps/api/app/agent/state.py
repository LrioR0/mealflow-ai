from typing import Any, TypedDict


class MealPlanningState(TypedDict, total=False):
    workspace_id: str
    site_id: str
    meal_service_id: str
    request_text: str
    constraints: dict[str, Any]
    inventory_snapshot: list[dict[str, Any]]
    feedback_summary: dict[str, Any]
    candidate_recipes: list[dict[str, Any]]
    menu_options: list[dict[str, Any]]
    selected_option: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    warnings: list[str]
    approval_status: str
