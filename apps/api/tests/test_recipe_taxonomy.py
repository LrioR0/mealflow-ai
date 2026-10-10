from decimal import Decimal

from sqlalchemy import select, text

from app.db.models import Recipe
from app.db.session import SessionLocal
from app.services.recipe_taxonomy import (
    IngredientFact,
    backfill_recipe_classifications,
    classify_recipe,
)


def _fact(
    key: str, name: str, category: str, quantity: str = "1", unit: str = "份"
) -> IngredientFact:
    return IngredientFact(key, name, category, Decimal(quantity), unit, False)


def test_named_dishes_match_manual_roles() -> None:
    cases = {
        "家常汤面": ("complete_meal", "面食"),
        "大锅米饭": ("staple_side", "米饭"),
        "黄焖鸡米饭": ("complete_meal", "米饭"),
        "洋葱炒蛋": ("mixed_dish", "无"),
        "清炒时蔬": ("vegetable_dish", "无"),
    }
    ingredients = {
        "家常汤面": [
            _fact("noodles", "挂面", "主食"),
            _fact("greens", "青菜", "蔬菜"),
            _fact("egg", "鸡蛋", "蛋奶"),
        ],
        "大锅米饭": [_fact("rice", "大米", "主食", "0.55", "kg")],
        "黄焖鸡米饭": [_fact("chicken_leg", "鸡腿", "肉禽"), _fact("rice", "大米", "主食")],
        "洋葱炒蛋": [_fact("onion", "洋葱", "蔬菜"), _fact("egg", "鸡蛋", "蛋奶")],
        "清炒时蔬": [_fact("greens", "青菜", "蔬菜")],
    }
    for name, expected in cases.items():
        classified = classify_recipe(name, [], ingredients[name])
        assert (classified.meal_role, classified.staple_type) == expected


def test_incomplete_recipe_is_not_composable() -> None:
    classified = classify_recipe("神秘调味", [], [_fact("salt", "盐", "调料")])
    assert classified.meal_role == ""
    assert classified.composable is False


def test_seed_recipes_have_roles() -> None:
    with SessionLocal() as session:
        recipes = session.scalars(select(Recipe)).all()
        by_name = {item.name: item for item in recipes}
    blank = [item.name for item in recipes if not item.meal_role]
    assert blank == []
    assert by_name["番茄炒蛋"].meal_role == "mixed_dish"
    assert by_name["牛奶馒头"].meal_role == "staple_side"
    assert by_name["豆角焖面"].staple_type == "面食"


def test_backfill_reclassifies_cleared_roles() -> None:
    with SessionLocal() as session:
        session.execute(text("UPDATE recipes SET meal_role = ''"))
        session.commit()
        backfill_recipe_classifications(session.connection())
        session.commit()
        row = session.execute(
            text("SELECT meal_role, staple_type FROM recipes WHERE name = '家常汤面'")
        ).one()
    assert row.meal_role == "complete_meal"
    assert row.staple_type == "面食"
