"""家庭常备料策略。

常备料不是库存：它默认可用、不进入缺货或采购建议，但仍是完整菜谱和
过敏/忌口校验的一部分。这里集中维护该规则，避免聊天与正式配餐各自判断。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import HouseholdPantryConfig


DEFAULT_PANTRY_STAPLE_KEYS = frozenset({
    "salt", "sugar", "oil", "soy_sauce", "dark_soy_sauce", "oyster_sauce",
    "vinegar", "starch", "peppercorn", "scallion", "ginger", "garlic",
    "cooking_wine", "pepper", "dried_chili", "doubanjiang",
})


def effective_pantry_keys(session: Session | None, workspace_id: str) -> set[str]:
    """返回默认库经家庭覆盖后的有效常备料 key。"""
    config = session.get(HouseholdPantryConfig, workspace_id) if session else None
    if config is None:
        return set(DEFAULT_PANTRY_STAPLE_KEYS)
    keys = set(DEFAULT_PANTRY_STAPLE_KEYS) if config.use_defaults else set()
    keys.update(config.custom_keys or [])
    keys.difference_update(config.disabled_default_keys or [])
    return keys
