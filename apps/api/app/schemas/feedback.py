"""反馈聚合契约（docs/api.md：GET /feedback/summary、每日菜单与反馈）。"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class DishFeedbackStat(BaseModel):
    dish: str
    avg_rating: float
    sample_count: int
    top_tags: list[str] = Field(default_factory=list)


class FeedbackSummaryView(BaseModel):
    workspace_id: str
    meal_service_id: str
    sample_count: int
    suspicious_count: int
    avg_rating: float | None = None
    top_tags: list[str] = Field(default_factory=list)
    tag_counts: dict[str, int] = Field(default_factory=dict)
    leftover_levels: dict[str, int] = Field(default_factory=dict)
    comment_digest: list[str] = Field(default_factory=list)
    dishes: list[DishFeedbackStat] = Field(default_factory=list)


class DailyFeedbackEntry(BaseModel):
    rating: int
    tags: list[str] = Field(default_factory=list)
    comment: str | None = None
    leftover_level: str | None = None
    submitted_at: datetime


class FeedbackDigest(BaseModel):
    """反馈超过展示上限时的自动概括（评分终端设计 §4：排除可疑批次）。"""

    sample_count: int
    avg_rating: float | None = None
    top_tags: list[str] = Field(default_factory=list)
    comment_digest: list[str] = Field(default_factory=list)


class DailyFeedbackDay(BaseModel):
    """运营概览：某天的菜单与该天反馈；反馈多于 FULL_DISPLAY_LIMIT 条时只给概括。"""

    date: date
    meal_service_id: str
    meal_service_name: str
    dishes: list[str] = Field(default_factory=list)
    feedback_count: int
    entries: list[DailyFeedbackEntry] | None = None
    summary: FeedbackDigest | None = None
