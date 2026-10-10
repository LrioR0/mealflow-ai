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
    # 家庭档案扩展:性别/常驻或访客/忌口(自由文本)/备注(特殊事件)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    residency: Mapped[str] = mapped_column(String(10), default="resident")
    taboo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    status: Mapped[str] = mapped_column(String(32), default="active")


class HouseholdPantryConfig(TimestampMixin, Base):
    """工作区级常备料覆盖；默认项不必逐条落库。"""

    __tablename__ = "household_pantry_configs"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    use_defaults: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_default_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    custom_keys: Mapped[list[str]] = mapped_column(JSON, default=list)


class DietaryRestriction(TimestampMixin, Base):
    __tablename__ = "dietary_restrictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    # 家庭模式:user_id 为空表示全家共享限制,否则为成员个人忌口/过敏
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    ingredient_key: Mapped[str] = mapped_column(String(80))


class MemberEvent(TimestampMixin, Base):
    """家庭成员的特殊事件(例假/感冒等),带生效日期,到期自动失效。"""

    __tablename__ = "member_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    constraint_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


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
    # 采购成本按市区大型超市参考价计算,金额输出必须携带来源标注
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_source: Mapped[str] = mapped_column(
        String(120), default="市区大型超市公开参考价"
    )
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    # 口味维度 tags(辛辣/油腻/生冷/清淡/海鲜/温补),与成员约束做冲突检测
    taste_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    allergens: Mapped[list[str]] = mapped_column(JSON, default=list)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_name: Mapped[str] = mapped_column(String(160), default="自制演示数据")
    source_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    license_note: Mapped[str] = mapped_column(
        String(200), default="自制演示数据，仅用于演示，可再分发"
    )
    meal_role: Mapped[str] = mapped_column(String(32), default="", server_default="")
    staple_type: Mapped[str] = mapped_column(String(16), default="无", server_default="无")
    protein_sources: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    vegetable_keys: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    portion_confidence: Mapped[str] = mapped_column(
        String(32), default="servings_only", server_default="servings_only"
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


class AgentChatSession(TimestampMixin, Base):
    """对话式工作台的会话,多轮消息围绕一个会话展开。"""

    __tablename__ = "agent_chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="新会话")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AgentChatMessage(TimestampMixin, Base):
    """会话消息。assistant 消息保存思维链回看与关联的运行/方案。"""

    __tablename__ = "agent_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    thinking_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("meal_plans.id"), nullable=True)


class ProcurementItem(TimestampMixin, Base):
    """家庭共享采购清单项。"""

    __tablename__ = "procurement_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    ingredient: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[str] = mapped_column(String(40), default="—")
    unit: Mapped[str] = mapped_column(String(20), default="份")
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CookingRecord(TimestampMixin, Base):
    """家庭共享下厨足迹文字记录；图片暂由前端本地保留。"""

    __tablename__ = "cooking_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    dish_name: Mapped[str] = mapped_column(String(120), index=True)
    cook: Mapped[str] = mapped_column(String(80))
    cooked_at: Mapped[str] = mapped_column(String(40))
    servings: Mapped[int] = mapped_column(Integer, default=1)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    difficulty: Mapped[str] = mapped_column(String(20), default="家常")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    ingredients: Mapped[str] = mapped_column(Text, default="")
    story: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    rating: Mapped[float] = mapped_column(Numeric(3, 1), default=5)
    next_time_note: Mapped[str] = mapped_column(Text, default="")
    image: Mapped[str] = mapped_column(Text, default="")
    reviews: Mapped[list[dict]] = mapped_column(JSON, default=list)

