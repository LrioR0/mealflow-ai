from datetime import date, timedelta

from sqlalchemy import func, select

from app.db.models import (
    DietaryRestriction,
    Ingredient,
    InventoryItem,
    KioskDevice,
    MealService,
    Recipe,
    User,
    Workspace,
)
from app.db.seed import DEMO_KIOSK_TOKEN, seed_demo_data
from app.db.session import SessionLocal
from app.services.feedback_service import hash_device_token


def test_seed_is_idempotent_and_complete() -> None:
    seed_demo_data()
    seed_demo_data()

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Recipe)) >= 20
        assert session.scalar(select(func.count()).select_from(Ingredient)) >= 30

        restrictions = session.scalars(select(DietaryRestriction)).all()
        assert {(r.type, r.ingredient_key) for r in restrictions} == {
            ("allergy", "peanut"),
            ("dislike", "cilantro"),
        }


def test_seed_demo_scenario_matches_plan() -> None:
    """Day 1 演示标准：机关食堂、120 人午餐、临期番茄。"""
    seed_demo_data()

    with SessionLocal() as session:
        workspace = session.get(Workspace, "demo-workspace")
        assert workspace is not None and workspace.name == "示例机关食堂"

        meal_service = session.get(MealService, "demo-lunch")
        assert meal_service is not None
        assert meal_service.expected_diners == 120

        tomorrow = date.today() + timedelta(days=1)
        tomato = session.execute(
            select(InventoryItem)
            .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
            .where(Ingredient.key == "tomato")
        ).scalar_one()
        assert tomato.expires_on is not None
        assert tomato.expires_on <= tomorrow + timedelta(days=1)


def test_seed_recipes_are_traceable() -> None:
    """数据字典：每条种子菜谱须可追溯（来源、授权说明）。"""
    seed_demo_data()

    with SessionLocal() as session:
        recipes = session.scalars(select(Recipe)).all()
        for recipe in recipes:
            assert recipe.source_name, recipe.name
            assert recipe.license_note, recipe.name


def test_seed_creates_demo_kiosk_device() -> None:
    """评分终端设计：终端绑定站点，服务端只存令牌哈希。"""
    seed_demo_data()

    with SessionLocal() as session:
        device = session.scalar(
            select(KioskDevice).where(KioskDevice.device_id == "kiosk-demo-01")
        )
        assert device is not None
        assert device.workspace_id == "demo-workspace"
        assert device.site_id == "demo-site"
        assert device.token_hash == hash_device_token(DEMO_KIOSK_TOKEN)
        assert device.status == "active"
