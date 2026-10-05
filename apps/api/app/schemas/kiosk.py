"""Kiosk 终端契约（docs/api.md、docs/评分终端设计.md）。

终端以受限设备令牌读取已发布菜单、提交匿名反馈；请求不携带用户身份。
反馈定位（餐次/菜单）由服务端按设备绑定站点与已发布菜单解析，
请求体只携带评分、标签、可选备注、剩余等级与幂等键。
"""

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=300)
    leftover_level: str | None = Field(default=None, max_length=32)
    idempotency_key: str | None = Field(default=None, max_length=80)


class FeedbackAccepted(BaseModel):
    id: str
    reset_after_seconds: int = 3


class KioskMenuItem(BaseModel):
    name: str
    kcal_per_serving: int | None = None
    allergens: list[str] = Field(default_factory=list)


class KioskMenuView(BaseModel):
    meal_service: dict
    plan_id: str
    strategy: str
    menu: list[KioskMenuItem]
