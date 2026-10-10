from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


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
    ingredient_key: str | None = Field(default=None, max_length=80)
    ingredient_name: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    quantity: Decimal = Field(gt=0, description="数量必须大于 0")
    unit: str | None = Field(default=None, max_length=20)
    expires_on: date | None = None

    @model_validator(mode="after")
    def validate_ingredient_reference(self) -> "InventoryCreate":
        self.ingredient_key = (self.ingredient_key or "").strip() or None
        self.ingredient_name = (self.ingredient_name or "").strip() or None
        self.category = (self.category or "").strip() or None
        self.unit = (self.unit or "").strip() or None
        if self.ingredient_key is None and not all(
            (self.ingredient_name, self.category, self.unit)
        ):
            raise ValueError("创建自定义食材时必须填写名称、类别和单位")
        return self


class InventoryUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, ge=0, description="数量不得小于 0")
    unit: str | None = Field(default=None, max_length=20)
    expires_on: date | None = None


class IngredientView(BaseModel):
    key: str
    name: str
    category: str
    default_unit: str
