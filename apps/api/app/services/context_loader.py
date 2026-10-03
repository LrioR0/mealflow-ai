"""规划上下文加载：Agent 感知工具的数据来源。

按技术开发文档分层约定，Service 通过本模块读取数据，Rule Engine 保持无副作用。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DietaryRestriction,
    Feedback,
    Ingredient,
    InventoryItem,
    MealService,
    Recipe,
    RecipeIngredient,
    Site,
    Workspace,
)

EXPIRING_WINDOW_DAYS = 2


class ScopeNotFoundError(LookupError):
    """请求中的 workspace/site/meal_service 作用域在库中不存在。"""


@dataclass
class InventoryLine:
    key: str
    name: str
    quantity: Decimal
    unit: str
    expires_on: date | None

    def is_expiring(self, today: date) -> bool:
        return (
            self.expires_on is not None
            and self.expires_on <= today + timedelta(days=EXPIRING_WINDOW_DAYS)
        )


@dataclass
class RecipeIngredientLine:
    key: str
    name: str
    quantity: Decimal
    unit: str
    optional: bool


@dataclass
class RecipeContext:
    id: str
    name: str
    servings: int
    duration_minutes: int
    kcal_per_serving: int | None
    estimated_cost_cents: int | None
    tags: list[str]
    allergens: list[str]
    ingredients: list[RecipeIngredientLine] = field(default_factory=list)

    @property
    def required_ingredient_keys(self) -> set[str]:
        return {line.key for line in self.ingredients if not line.optional}


@dataclass
class PlanningContext:
    workspace_id: str
    workspace_name: str
    site_name: str
    meal_service_id: str
    meal_service_name: str
    service_date: date
    expected_diners: int
    budget_limit_cents: int | None
    inventory: list[InventoryLine]
    recipes: list[RecipeContext]
    excluded_keys: list[str]
    feedback_count: int
    feedback_avg_rating: float | None
    feedback_top_tags: list[str]

    def expiring_keys(self, today: date) -> set[str]:
        return {line.key for line in self.inventory if line.is_expiring(today)}

    def available_for(self, ingredient_key: str) -> Decimal:
        for line in self.inventory:
            if line.key == ingredient_key:
                return line.quantity
        return Decimal("0")

    def inventory_unit(self, ingredient_key: str) -> str | None:
        for line in self.inventory:
            if line.key == ingredient_key:
                return line.unit
        return None


def load_planning_context(
    session: Session, workspace_id: str, site_id: str, meal_service_id: str
) -> PlanningContext:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise ScopeNotFoundError(f"workspace {workspace_id} 不存在")
    site = session.get(Site, site_id)
    if site is None or site.workspace_id != workspace.id:
        raise ScopeNotFoundError(f"site {site_id} 不存在或不属于该工作区")
    meal_service = session.get(MealService, meal_service_id)
    if meal_service is None or meal_service.site_id != site.id:
        raise ScopeNotFoundError(f"meal_service {meal_service_id} 不存在或不属于该站点")

    # 库存
    inventory: list[InventoryLine] = []
    rows = session.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.workspace_id == workspace.id)
    ).all()
    for item, ingredient in rows:
        if item.quantity <= 0:
            continue
        inventory.append(
            InventoryLine(
                key=ingredient.key,
                name=ingredient.name,
                quantity=item.quantity,
                unit=item.unit,
                expires_on=item.expires_on,
            )
        )

    # 菜谱与配方明细
    recipes: list[RecipeContext] = []
    recipe_rows = session.scalars(select(Recipe)).all()
    links = session.execute(
        select(RecipeIngredient, Ingredient)
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .order_by(RecipeIngredient.recipe_id)
    ).all()
    ingredients_by_recipe: dict[str, list[RecipeIngredientLine]] = {}
    for link, ingredient in links:
        ingredients_by_recipe.setdefault(link.recipe_id, []).append(
            RecipeIngredientLine(
                key=ingredient.key,
                name=ingredient.name,
                quantity=link.quantity,
                unit=link.unit,
                optional=link.optional,
            )
        )
    for recipe in recipe_rows:
        recipes.append(
            RecipeContext(
                id=recipe.id,
                name=recipe.name,
                servings=recipe.servings,
                duration_minutes=recipe.duration_minutes,
                kcal_per_serving=recipe.kcal_per_serving,
                estimated_cost_cents=recipe.estimated_cost_cents,
                tags=recipe.tags,
                allergens=recipe.allergens,
                ingredients=ingredients_by_recipe.get(recipe.id, []),
            )
        )

    # 用餐限制（过敏原与忌口，硬过滤）
    excluded_keys = list(
        session.scalars(
            select(DietaryRestriction.ingredient_key).where(
                DietaryRestriction.workspace_id == workspace.id
            )
        )
    )

    # 历史反馈摘要（Day 3 完整聚合，当前仅读取规模）
    feedback_rows = session.scalars(select(Feedback)).all()
    feedback_count = len(feedback_rows)
    ratings = [row.rating for row in feedback_rows]
    avg_rating = sum(ratings) / len(ratings) if ratings else None
    tag_counter: dict[str, int] = {}
    for row in feedback_rows:
        for tag in row.tags or []:
            tag_counter[tag] = tag_counter.get(tag, 0) + 1
    top_tags = [tag for tag, _ in sorted(tag_counter.items(), key=lambda kv: -kv[1])[:3]]

    return PlanningContext(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        site_name=site.name,
        meal_service_id=meal_service.id,
        meal_service_name=meal_service.name,
        service_date=meal_service.service_date,
        expected_diners=meal_service.expected_diners,
        budget_limit_cents=meal_service.budget_limit_cents,
        inventory=inventory,
        recipes=recipes,
        excluded_keys=excluded_keys,
        feedback_count=feedback_count,
        feedback_avg_rating=avg_rating,
        feedback_top_tags=top_tags,
    )
