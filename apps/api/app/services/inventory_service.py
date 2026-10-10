"""库存服务：库存项的查询与维护（Agent 决策与库存页共用同一数据源）。"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, InventoryItem, Workspace
from app.schemas.inventory import InventoryCreate, InventoryItemView, InventoryUpdate

EXPIRING_WINDOW_DAYS = 2


class WorkspaceNotFoundError(LookupError):
    pass


class ItemNotFoundError(LookupError):
    pass


class IngredientNotFoundError(LookupError):
    pass


class UnitMismatchError(ValueError):
    pass


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _to_view(session: Session, item: InventoryItem, ingredient: Ingredient) -> InventoryItemView:
    expires_on = item.expires_on
    is_expiring = expires_on is not None and expires_on <= date.today() + timedelta(
        days=EXPIRING_WINDOW_DAYS
    )
    return InventoryItemView(
        id=item.id,
        ingredient_key=ingredient.key,
        ingredient_name=ingredient.name,
        category=ingredient.category,
        quantity=_format_decimal(item.quantity),
        unit=item.unit,
        expires_on=expires_on,
        is_expiring=is_expiring,
    )


def _get_ingredient(session: Session, key: str) -> Ingredient:
    ingredient = session.scalar(select(Ingredient).where(Ingredient.key == key))
    if ingredient is None:
        raise IngredientNotFoundError(f"食材 {key} 不存在")
    return ingredient


def _resolve_ingredient(session: Session, payload: InventoryCreate) -> Ingredient:
    """解析已有食材，或为用户输入创建可被 Agent 识别的自定义食材。"""
    if payload.ingredient_key:
        return _get_ingredient(session, payload.ingredient_key)

    name = payload.ingredient_name or ""
    existing = session.scalar(select(Ingredient).where(Ingredient.name == name))
    if existing is not None:
        return existing

    ingredient = Ingredient(
        key=f"custom_{uuid4().hex}",
        name=name,
        category=payload.category or "其他",
        default_unit=payload.unit or "份",
        reference_price=None,
        price_source="用户自定义食材，暂无参考价",
    )
    session.add(ingredient)
    session.flush()
    return ingredient


def list_items(session: Session, workspace_id: str) -> list[InventoryItemView]:
    if session.get(Workspace, workspace_id) is None:
        raise WorkspaceNotFoundError(f"工作区 {workspace_id} 不存在")
    rows = session.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.workspace_id == workspace_id)
        .order_by(InventoryItem.expires_on.nulls_last(), Ingredient.name)
    ).all()
    return [_to_view(session, item, ingredient) for item, ingredient in rows]


def add_item(session: Session, workspace_id: str, payload: InventoryCreate) -> InventoryItemView:
    """新增库存项；同一食材已存在时按数据字典语义更新为最新数量（upsert）。"""
    if session.get(Workspace, workspace_id) is None:
        raise WorkspaceNotFoundError(f"工作区 {workspace_id} 不存在")
    ingredient = _resolve_ingredient(session, payload)
    unit = payload.unit or ingredient.default_unit
    if unit != ingredient.default_unit:
        raise UnitMismatchError(
            f"单位 {unit} 与食材默认单位 {ingredient.default_unit} 不一致，无法安全换算，需人工确认"
        )
    item = session.scalar(
        select(InventoryItem).where(
            InventoryItem.workspace_id == workspace_id,
            InventoryItem.ingredient_id == ingredient.id,
        )
    )
    if item is None:
        item = InventoryItem(workspace_id=workspace_id, ingredient_id=ingredient.id)
        session.add(item)
    item.quantity = payload.quantity
    item.unit = unit
    item.expires_on = payload.expires_on
    session.commit()
    return _to_view(session, item, ingredient)


def update_item(
    session: Session, item_id: str, payload: InventoryUpdate
) -> InventoryItemView:
    item = session.get(InventoryItem, item_id)
    if item is None:
        raise ItemNotFoundError(f"库存项 {item_id} 不存在")
    ingredient = session.get(Ingredient, item.ingredient_id)
    fields = payload.model_fields_set
    if "quantity" in fields and payload.quantity is not None:
        item.quantity = payload.quantity
    if "unit" in fields and payload.unit is not None:
        if ingredient and payload.unit != ingredient.default_unit:
            raise UnitMismatchError(
                f"单位 {payload.unit} 与食材默认单位 {ingredient.default_unit} 不一致，需人工确认"
            )
        item.unit = payload.unit
    if "expires_on" in fields:
        item.expires_on = payload.expires_on
    session.commit()
    return _to_view(session, item, ingredient)


def delete_item(session: Session, item_id: str) -> None:
    item = session.get(InventoryItem, item_id)
    if item is None:
        raise ItemNotFoundError(f"库存项 {item_id} 不存在")
    session.delete(item)
    session.commit()


def list_ingredients(session: Session) -> list[dict[str, str]]:
    rows = session.scalars(select(Ingredient).order_by(Ingredient.category, Ingredient.name)).all()
    return [
        {"key": i.key, "name": i.name, "category": i.category, "default_unit": i.default_unit}
        for i in rows
    ]
