from datetime import date
from decimal import Decimal

from app.services.context_loader import (
    FoodPreferenceContext,
    InventoryLine,
    MemberConstraint,
    PlanningContext,
    RecipeContext,
    RecipeIngredientLine,
)
from app.services.menu_composer import compose_menu


def _line(key: str, name: str, quantity: str = "1", unit: str = "份") -> RecipeIngredientLine:
    return RecipeIngredientLine(key, name, Decimal(quantity), unit, False)


def _recipe(
    recipe_id: str,
    name: str,
    role: str,
    staple: str,
    ingredients: list[RecipeIngredientLine],
    sources: list[str] | None = None,
    servings: int = 2,
) -> RecipeContext:
    return RecipeContext(
        id=recipe_id,
        name=name,
        servings=servings,
        duration_minutes=15,
        kcal_per_serving=100,
        estimated_cost_cents=200,
        tags=[],
        taste_tags=[],
        allergens=[],
        ingredients=ingredients,
        meal_role=role,
        staple_type=staple,
        protein_sources=sources or [],
        portion_confidence="complete",
    )


def _context(
    recipes: list[RecipeContext], inventory: list[tuple[str, str]], diners: int = 2
) -> PlanningContext:
    return PlanningContext(
        workspace_id="workspace",
        workspace_name="家",
        site_name="厨房",
        meal_service_id="lunch",
        meal_service_name="午餐",
        service_date=date(2026, 10, 8),
        expected_diners=diners,
        budget_limit_cents=None,
        inventory=[InventoryLine(key, name, Decimal("1"), "份", None) for key, name in inventory],
        recipes=recipes,
        members=[],
        member_constraints=[],
        excluded_keys=[],
    )


def _kitchen() -> list[RecipeContext]:
    return [
        _recipe("chicken", "辣子鸡", "protein_dish", "无", [_line("chicken", "鸡肉")], ["鸡肉"]),
        _recipe("fish", "清蒸草鱼", "protein_dish", "无", [_line("fish", "草鱼")], ["鱼虾"]),
        _recipe("pork", "红烧肉", "protein_dish", "无", [_line("pork", "猪肉")], ["猪肉"]),
        _recipe("ribs", "糖醋排骨", "protein_dish", "无", [_line("pork", "猪肉")], ["猪肉"]),
        _recipe(
            "greens",
            "清炒时蔬",
            "vegetable_dish",
            "无",
            [_line("greens", "青菜", "0.4", "kg")],
            servings=4,
        ),
        _recipe("cucumber", "拍黄瓜", "vegetable_dish", "无", [_line("cucumber", "黄瓜")]),
        _recipe("soup", "紫菜蛋花汤", "soup", "无", [_line("egg", "鸡蛋")], ["蛋"]),
        _recipe(
            "rice",
            "大锅米饭",
            "staple_side",
            "米饭",
            [_line("rice", "大米", "0.55", "kg")],
            servings=4,
        ),
        _recipe(
            "noodle",
            "家常汤面",
            "complete_meal",
            "面食",
            [_line("noodles", "挂面"), _line("greens", "青菜")],
        ),
        _recipe("bread", "牛奶馒头", "staple_side", "面食", [_line("flour", "面粉")]),
        _recipe("shrimp", "白灼虾", "protein_dish", "无", [_line("shrimp", "虾仁")], ["鱼虾"]),
        _recipe("unknown", "神秘菜", "", "无", [_line("salt", "盐")]),
    ]


def test_two_people_get_one_meat_one_vegetable_and_rice() -> None:
    stock = [("chicken", "鸡肉"), ("greens", "青菜"), ("rice", "大米")]
    menu, _suggestions = compose_menu({}, _context(_kitchen(), stock), None)
    assert menu["meal_structure"] == "1 荤 + 1 素 + 米饭"
    assert menu["staple"]["suggested_quantity"] == "生米约 160g"
    assert menu["staple"]["cooked_quantity"] == "熟米饭约 380g"
    assert "0.55" not in menu["staple"]["suggested_quantity"]
    assert {item["role_label"] for item in menu["items"]} == {"荤菜", "素菜"}
    vegetable = next(item for item in menu["items"] if item["name"] == "清炒时蔬")
    assert vegetable["scaled_ingredients"][0]["display"] == "0.2kg"
    assert menu["portion_note"] == "份量为标准成人估算，可按饭量调整"


def test_noodle_meal_excludes_other_staples() -> None:
    menu, _suggestions = compose_menu(
        {"staple": "汤面"},
        _context(
            _kitchen(),
            [("chicken", "鸡肉"), ("greens", "青菜"), ("noodles", "挂面"), ("rice", "大米")],
        ),
        None,
    )
    assert menu["staple"]["name"] == "家常汤面"
    assert menu["staple"]["type"] == "面食"
    assert menu["staple"]["suggested_quantity"] == "干面约 200g"
    names = {item["name"] for item in menu["items"]}
    assert "大锅米饭" not in names
    assert "牛奶馒头" not in names
    assert "家常汤面" not in names


def test_four_dishes_and_soup_keep_staple_separate() -> None:
    menu, _suggestions = compose_menu(
        {"diners": 4, "dish_count": 4, "need_soup": True, "staple": "米饭"},
        _context(
            _kitchen(),
            [
                ("chicken", "鸡肉"),
                ("fish", "草鱼"),
                ("greens", "青菜"),
                ("cucumber", "黄瓜"),
                ("egg", "鸡蛋"),
                ("rice", "大米"),
            ],
            4,
        ),
        None,
    )
    assert menu["meal_structure"] == "2 荤 + 2 素 + 1 汤 + 米饭"
    assert sum(item["role"] == "soup" for item in menu["items"]) == 1
    assert len([item for item in menu["items"] if item["role"] != "soup"]) == 4
    assert menu["staple"]["suggested_quantity"] == "生米约 320g"
    assert all(item["role"] not in {"staple_side", "complete_meal"} for item in menu["items"])


def test_meat_only_inventory_still_lists_vegetable_to_buy() -> None:
    menu, suggestions = compose_menu({}, _context(_kitchen(), [("chicken", "鸡肉")]), None)
    vegetable = next(item for item in menu["items"] if item["role_label"] == "素菜")
    assert vegetable["state"] == "purchase_optional"
    assert "青菜" in vegetable["missing_main_ingredients"]
    assert "青菜" not in vegetable["used_inventory"]
    assert any(item["ingredient"] == "青菜" for item in suggestions)


def test_vegetable_only_inventory_does_not_pretend_meat_exists() -> None:
    menu, _suggestions = compose_menu({}, _context(_kitchen(), [("greens", "青菜")]), None)
    protein = next(item for item in menu["items"] if item["role_label"] == "荤菜")
    assert protein["state"] == "purchase_optional"
    assert protein["used_inventory"] == []
    assert protein["missing_main_ingredients"]


def test_missing_vegetable_recipe_is_explained() -> None:
    recipes = [item for item in _kitchen() if item.meal_role != "vegetable_dish"]
    menu, _suggestions = compose_menu({}, _context(recipes, [("chicken", "鸡肉")]), None)
    assert all(item["role_label"] != "素菜" for item in menu["items"])
    assert any("还缺少一项蔬菜" in note for note in menu["relaxations"])


def test_incomplete_recipe_is_not_composed() -> None:
    stock = [("chicken", "鸡肉"), ("greens", "青菜")]
    menu, _suggestions = compose_menu({}, _context(_kitchen(), stock), None)
    assert all(item["name"] != "神秘菜" for item in menu["items"])


def test_allergen_and_pantry_rules() -> None:
    context = _context(_kitchen(), [("chicken", "鸡肉"), ("greens", "青菜")])
    context.member_constraints = [
        MemberConstraint("partner", "对象", "restriction", "forbidden", "对象·过敏虾仁", "shrimp")
    ]
    context.pantry_keys = {"oil"}
    context.recipes.append(
        _recipe(
            "oil-chicken",
            "油淋鸡",
            "protein_dish",
            "无",
            [_line("chicken", "鸡肉"), _line("oil", "食用油")],
            ["鸡肉"],
        )
    )
    menu, suggestions = compose_menu({}, context, None)
    assert all(item["name"] != "白灼虾" for item in menu["items"])
    assert all(item["ingredient"] != "食用油" for item in suggestions)


def test_protein_diversity_avoids_two_pork_dishes() -> None:
    menu, _suggestions = compose_menu(
        {"diners": 4, "dish_count": 3},
        _context(_kitchen(), [("chicken", "鸡肉"), ("pork", "猪肉"), ("greens", "青菜")], 4),
        None,
    )
    proteins = [item["name"] for item in menu["items"] if item["role_label"] == "荤菜"]
    assert "辣子鸡" in proteins
    assert not ({"红烧肉", "糖醋排骨"} <= set(proteins))


def test_required_dish_is_locked_and_other_slots_are_filled() -> None:
    context = _context(_kitchen(), [("shrimp", "虾仁"), ("cucumber", "黄瓜"), ("rice", "大米")])
    menu, _suggestions = compose_menu(
        {"diners": 2, "required_dishes": ["辣子鸡"], "budget_limit_cents": 6000},
        context,
        None,
    )
    names = {item["name"] for item in menu["items"]}
    assert "辣子鸡" in names
    assert len([item for item in menu["items"] if item["role_label"] == "荤菜"]) == 1
    assert menu["constraint_snapshot"]["required_dishes"] == ["辣子鸡"]
    assert menu["constraint_snapshot"]["budget_limit_cents"] == 6000


def test_persistent_dish_dislike_excludes_arbitrary_recipe() -> None:
    context = _context(_kitchen(), [("cucumber", "黄瓜"), ("chicken", "鸡肉")])
    context.food_preferences = [
        FoodPreferenceContext("owner", "dish", "cucumber", "拍黄瓜", "dislike")
    ]
    menu, _suggestions = compose_menu({}, context, ["owner"])
    assert all(item["name"] != "拍黄瓜" for item in menu["items"])


def test_explicitly_requested_disliked_dish_is_kept_with_warning() -> None:
    context = _context(_kitchen(), [("cucumber", "黄瓜"), ("chicken", "鸡肉")])
    context.food_preferences = [
        FoodPreferenceContext("owner", "dish", "cucumber", "拍黄瓜", "dislike")
    ]
    menu, _suggestions = compose_menu(
        {"required_dishes": ["拍黄瓜"]}, context, ["owner"]
    )
    cucumber = next(item for item in menu["items"] if item["name"] == "拍黄瓜")
    assert any("明确点名" in warning for warning in cucumber["warnings"])


def test_required_dish_with_allergy_is_blocked() -> None:
    context = _context(_kitchen(), [("shrimp", "虾仁"), ("greens", "青菜")])
    context.member_constraints = [
        MemberConstraint("owner", "我", "restriction", "forbidden", "我·过敏虾仁", "shrimp")
    ]
    menu, _suggestions = compose_menu(
        {"required_dishes": ["白灼虾"]}, context, ["owner"]
    )
    assert all(item["name"] != "白灼虾" for item in menu["items"])
    assert menu["constraint_snapshot"]["blocked_required_dishes"] == ["白灼虾"]


def test_generated_recipe_allergen_metadata_is_deterministically_blocked() -> None:
    recipes = _kitchen()
    generated = _recipe(
        "generated-dessert",
        "任意模型甜品",
        "mixed_dish",
        "无",
        [_line("generated:syrup", "糖浆")],
    )
    generated.source = "model_generated"
    generated.allergens = ["虾仁"]
    recipes.append(generated)
    context = _context(recipes, [("generated:syrup", "糖浆")])
    context.member_constraints = [
        MemberConstraint("owner", "我", "restriction", "forbidden", "我·过敏虾仁", "shrimp")
    ]

    menu, _suggestions = compose_menu(
        {"required_dishes": ["任意模型甜品"]}, context, ["owner"]
    )

    assert all(item["name"] != "任意模型甜品" for item in menu["items"])
    assert menu["constraint_snapshot"]["blocked_required_dishes"] == ["任意模型甜品"]
