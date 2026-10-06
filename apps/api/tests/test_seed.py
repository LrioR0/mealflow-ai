from datetime import date, timedelta

from sqlalchemy import func, select

from app.db.models import (
    DietaryRestriction,
    Ingredient,
    InventoryItem,
    MealService,
    MemberEvent,
    Recipe,
    User,
    Workspace,
)
from app.db.seed import seed_demo_data
from app.db.session import SessionLocal


def test_seed_is_idempotent_and_complete() -> None:
    seed_demo_data()
    seed_demo_data()

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1
        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Recipe)) >= 20
        assert session.scalar(select(func.count()).select_from(Ingredient)) >= 30
        assert session.scalar(select(func.count()).select_from(MemberEvent)) == 2

        restrictions = session.scalars(select(DietaryRestriction)).all()
        assert {(r.user_id, r.type, r.ingredient_key) for r in restrictions} == {
            ("home-partner", "dislike", "cilantro"),
            ("home-partner", "allergy", "shrimp"),
        }


def test_seed_family_scenario_matches_plan() -> None:
    """家庭演示标准:2 名成员、特殊事件当日生效、临期番茄、超市参考价。"""
    seed_demo_data()

    with SessionLocal() as session:
        workspace = session.get(Workspace, "home-workspace")
        assert workspace is not None and workspace.name == "我家"

        meal_service = session.get(MealService, "home-lunch")
        assert meal_service is not None
        assert meal_service.expected_diners == 2

        today = date.today()
        events = session.scalars(select(MemberEvent)).all()
        assert {(e.user_id, e.event_type) for e in events} == {
            ("home-me", "感冒"),
            ("home-partner", "例假"),
        }
        for event in events:
            assert event.start_date <= today <= event.end_date

        names = {user.display_name for user in session.scalars(select(User)).all()}
        assert names == {"我", "对象", "老李"}
        guest = session.scalar(select(User).where(User.display_name == "老李"))
        assert guest.residency == "guest"

        tomorrow = date.today() + timedelta(days=1)
        tomato = session.execute(
            select(InventoryItem)
            .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
            .where(Ingredient.key == "tomato")
        ).scalar_one()
        assert tomato.expires_on is not None
        assert tomato.expires_on <= tomorrow

        egg_ref_price = session.execute(
            select(Ingredient.reference_price).where(Ingredient.key == "egg")
        ).scalar_one()
        assert egg_ref_price is not None and egg_ref_price > 0


def test_seed_recipes_are_traceable_and_taste_tagged() -> None:
    """数据字典:每条种子菜谱须可追溯;关键菜谱带口味 tags 供冲突检测。"""
    seed_demo_data()

    with SessionLocal() as session:
        recipes = session.scalars(select(Recipe)).all()
        for recipe in recipes:
            assert recipe.source_name, recipe.name
            assert recipe.license_note, recipe.name

        by_name = {recipe.name: recipe for recipe in recipes}
        laziji = by_name.get("辣子鸡")
        assert laziji is not None
        assert "辛辣" in (laziji.taste_tags or [])
        assert laziji.steps, "辣子鸡必须带食谱步骤"
        douimian = by_name.get("豆角焖面")
        assert douimian is not None
