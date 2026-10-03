from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    meal_service_id: str
    meal_plan_id: str
    rating: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=300)
    leftover_level: str | None = None


class FeedbackAccepted(BaseModel):
    id: str
    reset_after_seconds: int = 3
