from datetime import datetime

from pydantic import BaseModel, Field


class ProcurementItemView(BaseModel):
    id: str
    workspace_id: str
    ingredient: str
    quantity: str
    unit: str
    checked: bool
    source: str
    source_id: str | None
    checked_at: datetime | None


class ProcurementItemCreate(BaseModel):
    workspace_id: str = "home-workspace"
    ingredient: str = Field(min_length=1, max_length=120)
    quantity: str = Field(default="—", max_length=40)
    unit: str = Field(default="份", max_length=20)
    checked: bool = False
    source: str = Field(default="manual", pattern="^(manual|agent)$")
    source_id: str | None = Field(default=None, max_length=120)


class ProcurementItemUpdate(BaseModel):
    ingredient: str | None = Field(default=None, min_length=1, max_length=120)
    quantity: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=20)
    checked: bool | None = None


class CookingRecordView(BaseModel):
    id: str
    workspace_id: str
    dish_name: str
    cook: str
    cooked_at: str
    servings: int
    duration_minutes: int
    difficulty: str
    tags: list[str]
    ingredients: str
    story: str
    steps: list[dict]
    rating: float
    next_time_note: str
    image: str
    reviews: list[dict]


class CookingRecordCreate(BaseModel):
    workspace_id: str = "home-workspace"
    dish_name: str = Field(min_length=1, max_length=120)
    cook: str = Field(min_length=1, max_length=80)
    cooked_at: str = Field(min_length=1, max_length=40)
    servings: int = Field(default=1, gt=0, le=100)
    duration_minutes: int = Field(default=30, gt=0, le=1000)
    difficulty: str = Field(default="家常", max_length=20)
    tags: list[str] = Field(default_factory=list)
    ingredients: str = Field(default="", max_length=5000)
    story: str = Field(default="", max_length=2000)
    steps: list[dict] = Field(default_factory=list)
    rating: float = Field(default=5, ge=0, le=5)
    next_time_note: str = Field(default="", max_length=2000)
    image: str = Field(default="", max_length=5_000_000)
    reviews: list[dict] = Field(default_factory=list)


class CookingRecordUpdate(BaseModel):
    dish_name: str | None = Field(default=None, min_length=1, max_length=120)
    cook: str | None = Field(default=None, min_length=1, max_length=80)
    cooked_at: str | None = Field(default=None, max_length=40)
    servings: int | None = Field(default=None, gt=0, le=100)
    duration_minutes: int | None = Field(default=None, gt=0, le=1000)
    difficulty: str | None = Field(default=None, max_length=20)
    tags: list[str] | None = None
    ingredients: str | None = Field(default=None, max_length=5000)
    story: str | None = Field(default=None, max_length=2000)
    steps: list[dict] | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    next_time_note: str | None = Field(default=None, max_length=2000)
    image: str | None = Field(default=None, max_length=5_000_000)
    reviews: list[dict] | None = None
