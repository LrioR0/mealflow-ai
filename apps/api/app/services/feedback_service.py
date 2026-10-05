"""Kiosk 反馈服务：设备令牌校验、匿名反馈持久化、防刷与聚合（docs/评分终端设计.md）。

- 设备令牌仅存哈希，明文只在注册时展示一次；令牌不能调用管理端接口。
- 提交成功后按设备冷却（与终端 3 秒重置时间一致），重复内容打可疑标记而非删除。
- 聚合按餐次与菜品统计平均分、标签、剩余等级与备注安全摘要，排除可疑批次。
- 原始备注不拼接进 Agent 提示词，只提供规则标签与安全摘要。
"""

import hashlib
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Feedback,
    KioskDevice,
    MealPlan,
    MealService,
    Recipe,
    Site,
)
from app.db.session import SessionLocal
from app.schemas.feedback import (
    DailyFeedbackDay,
    DailyFeedbackEntry,
    DishFeedbackStat,
    FeedbackDigest,
    FeedbackSummaryView,
)
from app.schemas.kiosk import FeedbackAccepted, FeedbackCreate, KioskMenuItem, KioskMenuView
from app.services.meal_plan_service import latest_published_plan_for_site

# 提交冷却与终端感谢页时长一致；窗口内的重复内容只标记不删除
FEEDBACK_COOLDOWN_SECONDS = 3
SUSPICIOUS_WINDOW_SECONDS = 60
COMMENT_DIGEST_LIMIT = 3
COMMENT_DIGEST_CHARS = 80
# 运营概览：反馈超过该条数时自动概括而不是逐条展示
DAILY_FEEDBACK_FULL_DISPLAY_LIMIT = 10
DAILY_FEEDBACK_DAY_LIMIT = 7


class KioskAuthError(PermissionError):
    """设备令牌缺失、无效或设备已停用。"""


class RateLimitedError(RuntimeError):
    """同一设备在冷却时间内重复提交。"""


class NoPublishedMenuError(RuntimeError):
    """设备绑定站点尚无已发布菜单，不能提交反馈。"""


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _resolve_device(session: Session, token: str | None) -> KioskDevice:
    if token:
        device = session.scalar(
            select(KioskDevice).where(KioskDevice.token_hash == hash_device_token(token))
        )
        if device is None or device.status != "active":
            raise KioskAuthError("设备令牌无效或已停用")
        return device

    # 演示模式：未携带令牌时回退种子终端，便于本地联调（生产必须携带令牌）
    if get_settings().demo_mode:
        device = session.scalar(
            select(KioskDevice).where(KioskDevice.device_id == "kiosk-demo-01")
        )
        if device is not None:
            return device
    raise KioskAuthError("缺少 Kiosk 设备令牌")


def _touch_device(session: Session, device: KioskDevice) -> None:
    device.last_seen_at = datetime.now(timezone.utc)
    session.add(device)
    session.commit()


def current_menu(token: str | None) -> KioskMenuView:
    with SessionLocal() as session:
        device = _resolve_device(session, token)
        _touch_device(session, device)

        plan = latest_published_plan_for_site(session, device.site_id)
        if plan is None:
            raise NoPublishedMenuError("当前站点还没有已发布的菜单")

        names = [item["name"] for item in plan.items or []]
        allergens_by_name = {
            recipe.name: recipe.allergens
            for recipe in session.scalars(select(Recipe).where(Recipe.name.in_(names))).all()
        }
        meal_service = session.get(MealService, plan.meal_service_id)
        return KioskMenuView(
            meal_service={
                "name": meal_service.name if meal_service else "午餐",
                "expected_diners": meal_service.expected_diners if meal_service else 0,
                "status": plan.status,
            },
            plan_id=plan.id,
            strategy=plan.strategy,
            menu=[
                KioskMenuItem(
                    name=item["name"],
                    kcal_per_serving=item.get("kcal_per_serving")
                    or item.get("estimated_kcal_per_serving"),
                    allergens=allergens_by_name.get(item["name"], []),
                )
                for item in plan.items or []
            ],
        )


def _sanitize_comment(comment: str | None) -> str | None:
    """备注限长并脱敏：去除首尾空白与控制字符，作为不可信输入处理。"""
    if comment is None:
        return None
    cleaned = "".join(char for char in comment.strip() if char.isprintable())
    return cleaned or None


def _is_duplicate_submission(
    session: Session, device_id: str, payload: FeedbackCreate
) -> bool:
    window_start = datetime.now(timezone.utc) - timedelta(seconds=SUSPICIOUS_WINDOW_SECONDS)
    recent = session.scalars(
        select(Feedback).where(
            Feedback.device_id == device_id,
            Feedback.created_at >= window_start,
        )
    ).all()
    fingerprint = (payload.rating, tuple(sorted(payload.tags)), _sanitize_comment(payload.comment))
    for row in recent:
        same = (
            row.rating,
            tuple(sorted(row.tags or [])),
            _sanitize_comment(row.comment),
        )
        if same == fingerprint:
            return True
    return False


def submit_feedback(token: str | None, payload: FeedbackCreate) -> FeedbackAccepted:
    with SessionLocal() as session:
        device = _resolve_device(session, token)

        if payload.idempotency_key:
            existing = session.scalar(
                select(Feedback).where(
                    Feedback.device_id == device.id,
                    Feedback.idempotency_key == payload.idempotency_key,
                )
            )
            if existing is not None:
                return FeedbackAccepted(id=existing.id)  # 幂等重放

        last = session.scalar(
            select(Feedback)
            .where(Feedback.device_id == device.id)
            .order_by(Feedback.created_at.desc())
            .limit(1)
        )
        if last is not None:
            elapsed = datetime.now(timezone.utc) - _utc_aware(last.created_at)
            if elapsed.total_seconds() < FEEDBACK_COOLDOWN_SECONDS:
                raise RateLimitedError("提交过于频繁，请稍后再试")

        plan = latest_published_plan_for_site(session, device.site_id)
        if plan is None:
            raise NoPublishedMenuError("当前站点还没有已发布的菜单")

        is_suspicious = _is_duplicate_submission(session, device.id, payload)
        row = Feedback(
            device_id=device.id,
            meal_service_id=plan.meal_service_id,
            meal_plan_id=plan.id,
            rating=payload.rating,
            tags=payload.tags,
            comment=_sanitize_comment(payload.comment),
            leftover_level=payload.leftover_level,
            is_suspicious=is_suspicious,
            idempotency_key=payload.idempotency_key,
        )
        session.add(row)
        _touch_device(session, device)
        session.commit()
        return FeedbackAccepted(id=row.id)


def feedback_summary(workspace_id: str, meal_service_id: str) -> FeedbackSummaryView:
    with SessionLocal() as session:
        meal_service = session.get(MealService, meal_service_id)
        site = (
            session.get(Site, meal_service.site_id) if meal_service is not None else None
        )
        if site is None or site.workspace_id != workspace_id:
            raise LookupError(f"meal_service {meal_service_id} 不存在或不属于该工作区")

        rows = session.scalars(
            select(Feedback).where(Feedback.meal_service_id == meal_service.id)
        ).all()
        valid = [row for row in rows if not row.is_suspicious]
        suspicious_count = len(rows) - len(valid)

        ratings = [row.rating for row in valid]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

        tag_counts: dict[str, int] = {}
        leftover_levels: dict[str, int] = {}
        for row in valid:
            for tag in row.tags or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            if row.leftover_level:
                leftover_levels[row.leftover_level] = leftover_levels.get(row.leftover_level, 0) + 1
        top_tags = [tag for tag, _ in sorted(tag_counts.items(), key=lambda kv: -kv[1])[:5]]

        comment_digest = [
            sanitized
            for sanitized in (
                (row.comment[:COMMENT_DIGEST_CHARS] if row.comment else None) for row in valid
            )
            if sanitized
        ][:COMMENT_DIGEST_LIMIT]

        dishes = _dish_stats(session, valid)
        return FeedbackSummaryView(
            workspace_id=workspace_id,
            meal_service_id=meal_service.id,
            sample_count=len(valid),
            suspicious_count=suspicious_count,
            avg_rating=avg_rating,
            top_tags=top_tags,
            tag_counts=tag_counts,
            leftover_levels=leftover_levels,
            comment_digest=comment_digest,
            dishes=dishes,
        )


def _dish_stats(session: Session, rows: list[Feedback]) -> list[DishFeedbackStat]:
    """按菜品聚合：反馈挂在其对应菜单计划包含的每道菜上。"""
    plan_items: dict[str, list[str]] = {}
    plan_ids = {row.meal_plan_id for row in rows}
    for plan in session.scalars(select(MealPlan).where(MealPlan.id.in_(plan_ids))).all():
        plan_items[plan.id] = [item["name"] for item in plan.items or []]

    ratings: dict[str, list[int]] = {}
    tags: dict[str, dict[str, int]] = {}
    for row in rows:
        for dish in plan_items.get(row.meal_plan_id, []):
            ratings.setdefault(dish, []).append(row.rating)
            for tag in row.tags or []:
                dish_tags = tags.setdefault(dish, {})
                dish_tags[tag] = dish_tags.get(tag, 0) + 1

    stats = [
        DishFeedbackStat(
            dish=dish,
            avg_rating=round(sum(dish_ratings) / len(dish_ratings), 2),
            sample_count=len(dish_ratings),
            top_tags=[
                tag for tag, _ in sorted(tags.get(dish, {}).items(), key=lambda kv: -kv[1])[:3]
            ],
        )
        for dish, dish_ratings in ratings.items()
    ]
    return sorted(stats, key=lambda stat: (-stat.sample_count, stat.dish))


def daily_feedback(workspace_id: str) -> list[DailyFeedbackDay]:
    """运营概览：按天返回已发布菜单与反馈；超过展示上限时只返回自动概括。"""
    with SessionLocal() as session:
        site_ids = session.scalars(
            select(Site.id).where(Site.workspace_id == workspace_id)
        ).all()
        if not site_ids:
            raise LookupError(f"workspace {workspace_id} 不存在或没有站点")

        services = session.scalars(
            select(MealService)
            .where(MealService.site_id.in_(site_ids))
            .order_by(MealService.service_date.desc())
            .limit(DAILY_FEEDBACK_DAY_LIMIT)
        ).all()

        days: list[DailyFeedbackDay] = []
        for service in services:
            published_plans = session.scalars(
                select(MealPlan)
                .where(MealPlan.meal_service_id == service.id, MealPlan.status == "published")
                .order_by(MealPlan.published_at.desc())
            ).all()
            dishes: list[str] = []
            for plan in published_plans:
                for item in plan.items or []:
                    if item["name"] not in dishes:
                        dishes.append(item["name"])

            rows = session.scalars(
                select(Feedback)
                .where(
                    Feedback.meal_service_id == service.id,
                    Feedback.is_suspicious == False,  # noqa: E712
                )
                .order_by(Feedback.created_at.asc())
            ).all()
            count = len(rows)

            if count > DAILY_FEEDBACK_FULL_DISPLAY_LIMIT:
                days.append(
                    DailyFeedbackDay(
                        date=service.service_date,
                        meal_service_id=service.id,
                        meal_service_name=service.name,
                        dishes=dishes,
                        feedback_count=count,
                        entries=None,
                        summary=_digest(rows, count),
                    )
                )
            else:
                days.append(
                    DailyFeedbackDay(
                        date=service.service_date,
                        meal_service_id=service.id,
                        meal_service_name=service.name,
                        dishes=dishes,
                        feedback_count=count,
                        entries=[
                            DailyFeedbackEntry(
                                rating=row.rating,
                                tags=row.tags or [],
                                comment=row.comment,
                                leftover_level=row.leftover_level,
                                submitted_at=row.created_at,
                            )
                            for row in rows
                        ],
                        summary=None,
                    )
                )
        return days


def _digest(rows: list[Feedback], count: int) -> FeedbackDigest:
    ratings = [row.rating for row in rows]
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in row.tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return FeedbackDigest(
        sample_count=count,
        avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        top_tags=[tag for tag, _ in sorted(tag_counts.items(), key=lambda kv: -kv[1])[:5]],
        comment_digest=[
            row.comment[:COMMENT_DIGEST_CHARS] for row in rows if row.comment
        ][:COMMENT_DIGEST_LIMIT],
    )
