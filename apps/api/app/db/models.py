from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceKind(StrEnum):
    ORGANIZATION = "organization"
    PERSONAL = "personal"


class AgentRunStatus(StrEnum):
    PARSING = "PARSING"
    RUNNING_TOOLS = "RUNNING_TOOLS"
    BUILDING_OPTIONS = "BUILDING_OPTIONS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PUBLISHED = "PUBLISHED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default=WorkspaceKind.ORGANIZATION.value)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    status: Mapped[str] = mapped_column(String(32), default="active")


class DietaryRestriction(TimestampMixin, Base):
    __tablename__ = "dietary_restrictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    ingredient_key: Mapped[str] = mapped_column(String(80))


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    service_capacity: Mapped[int] = mapped_column(Integer, default=0)


class MealService(TimestampMixin, Base):
    __tablename__ = "meal_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(40), default="午餐")
    service_date: Mapped[date] = mapped_column(Date)
    expected_diners: Mapped[int] = mapped_column(Integer)
    budget_limit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")


class Ingredient(TimestampMixin, Base):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(60))
    default_unit: Mapped[str] = mapped_column(String(20))


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(20))
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), index=True)
    servings: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    kcal_per_serving: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    allergens: Mapped[list[str]] = mapped_column(JSON, default=list)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_name: Mapped[str] = mapped_column(String(160), default="自制演示数据")
    source_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    license_note: Mapped[str] = mapped_column(
        String(200), default="自制演示数据，仅用于演示，可再分发"
    )


class RecipeIngredient(TimestampMixin, Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), index=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(20))
    optional: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    meal_service_id: Mapped[str] = mapped_column(ForeignKey("meal_services.id"), index=True)
    request_text: Mapped[str] = mapped_column(Text)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=AgentRunStatus.PARSING.value)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ToolTrace(TimestampMixin, Base):
    __tablename__ = "tool_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_summary: Mapped[str] = mapped_column(String(500), default="")
    output_summary: Mapped[str] = mapped_column(String(500), default="")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MealPlan(TimestampMixin, Base):
    __tablename__ = "meal_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    meal_service_id: Mapped[str] = mapped_column(ForeignKey("meal_services.id"), index=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(40))
    items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    procurement_list: Mapped[list[dict]] = mapped_column(JSON, default=list)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    # 数据字典：保存生成时的解释快照（约束与评分拆解），发布后不再变化
    constraints_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # api.md：发布接口必须使用 Idempotency-Key，同键重放返回同一结果
    publish_idempotency_key: Mapped[str | None] = mapped_column(
        String(80), unique=True, nullable=True
    )


class KioskDevice(TimestampMixin, Base):
    __tablename__ = "kiosk_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # 数据字典必填字段：device_id 标识物理终端，明文令牌只在注册时展示一次
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("kiosk_devices.id"), index=True)
    meal_service_id: Mapped[str] = mapped_column(ForeignKey("meal_services.id"), index=True)
    meal_plan_id: Mapped[str] = mapped_column(ForeignKey("meal_plans.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    leftover_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    # api.md：反馈请求携带幂等键，同键重放不产生重复记录
    idempotency_key: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
