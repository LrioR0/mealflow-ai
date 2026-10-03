from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class InventoryItemView(BaseModel):
    id: str
    ingredient_key: str
    ingredient_name: str
    category: str
    quantity: str
    unit: str
    expires_on: date | None
    is_expiring: bool


class InventoryCreate(BaseModel):
    ingredient_key: str
    quantity: Decimal = Field(gt=0, description="数量必须大于 0")
    unit: str | None = Field(default=None, max_length=20)
    expires_on: date | None = None


class InventoryUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, ge=0, description="数量不得小于 0")
    unit: str | None = Field(default=None, max_length=20)
    expires_on: date | None = None


class IngredientView(BaseModel):
    key: str
    name: str
    category: str
    default_unit: str
