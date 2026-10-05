"""种子数据脚本：预置演示机关食堂的完整数据闭环。

按数据字典（docs/数据字典.md）与三天开发计划 Day 1 要求：
- 示例机关食堂工作区、管理员账号、总部食堂站点、明日午餐餐次（120 人）
- 食材主数据、库存（含 2 天内到期的临期番茄）、用餐限制（过敏原/忌口硬过滤）
- data/seed/recipes.json 的可溯源种子菜谱

幂等：按天然键 upsert，可重复执行。运行：cd apps/api && python -m app.db.seed
"""

import json
import hashlib
import secrets
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DietaryRestriction,
    Ingredient,
    InventoryItem,
    KioskDevice,
    MealService,
    Recipe,
    RecipeIngredient,
    Site,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.session import SessionLocal
from app.services.feedback_service import hash_device_token

RECIPE_SEED_PATH = Path(__file__).resolve().parents[4] / "data" / "seed" / "recipes.json"

# 演示终端（评分终端设计 §3）：明文令牌仅在种子输出展示，服务端只存哈希
DEMO_KIOSK_DEVICE_ID = "kiosk-demo-01"
DEMO_KIOSK_TOKEN = "demo-kiosk-token"

INGREDIENTS: list[tuple[str, str, str, str]] = [
    # (key, name, category, default_unit)
    ("tomato", "番茄", "蔬菜", "kg"),
    ("potato", "土豆", "蔬菜", "kg"),
    ("greens", "青菜", "蔬菜", "kg"),
    ("pepper_green", "青椒", "蔬菜", "kg"),
    ("carrot", "胡萝卜", "蔬菜", "kg"),
    ("onion", "洋葱", "蔬菜", "kg"),
    ("mushroom", "香菇", "蔬菜", "kg"),
    ("cucumber", "黄瓜", "蔬菜", "kg"),
    ("eggplant", "茄子", "蔬菜", "kg"),
    ("winter_melon", "冬瓜", "蔬菜", "kg"),
    ("cilantro", "香菜", "蔬菜", "kg"),
    ("garlic", "大蒜", "蔬菜", "kg"),
    ("ginger", "生姜", "蔬菜", "kg"),
    ("scallion", "小葱", "蔬菜", "kg"),
    ("pork", "猪前腿肉", "肉禽", "kg"),
    ("chicken_breast", "鸡胸肉", "肉禽", "kg"),
    ("chicken_leg", "鸡腿", "肉禽", "kg"),
    ("beef", "牛腩", "肉禽", "kg"),
    ("egg", "鸡蛋", "蛋奶", "个"),
    ("milk", "牛奶", "蛋奶", "L"),
    ("fish", "草鱼", "水产", "kg"),
    ("shrimp", "虾仁", "水产", "kg"),
    ("tofu", "豆腐", "豆制品", "kg"),
    ("rice", "大米", "主食", "kg"),
    ("noodles", "挂面", "主食", "kg"),
    ("flour", "面粉", "主食", "kg"),
    ("peanut", "花生米", "坚果", "kg"),
    ("seaweed", "紫菜", "水产干货", "kg"),
    ("soy_sauce", "酱油", "调料", "L"),
    ("salt", "盐", "调料", "kg"),
    ("oil", "食用油", "调料", "L"),
    ("vinegar", "香醋", "调料", "L"),
    ("doubanjiang", "豆瓣酱", "调料", "kg"),
    ("starch", "淀粉", "调料", "kg"),
]

# (ingredient_key, quantity, unit, expires_after_days or None)
INVENTORY: list[tuple[str, Decimal, str, int | None]] = [
    ("tomato", Decimal("5"), "kg", 1),  # 明日到期：临期优先演示的关键数据
    ("tofu", Decimal("2"), "kg", 2),
    ("greens", Decimal("3"), "kg", 2),
    ("egg", Decimal("60"), "个", 3),
    ("chicken_leg", Decimal("4"), "kg", 3),
    ("pork", Decimal("3"), "kg", 3),
    ("potato", Decimal("8"), "kg", 7),
    ("rice", Decimal("20"), "kg", None),
    ("oil", Decimal("2"), "L", None),
    ("salt", Decimal("1"), "kg", None),
]

# 数据字典：allergy 与 dislike 均进入硬过滤
RESTRICTIONS: list[tuple[str, str]] = [
    ("allergy", "peanut"),
    ("dislike", "cilantro"),
]


def hash_demo_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2_sha256$100000${salt}${digest.hex()}"


def _get_or_create_ingredient(session: Session, key: str, name: str, category: str, unit: str) -> Ingredient:
    ingredient = session.scalar(select(Ingredient).where(Ingredient.key == key))
    if ingredient is None:
        ingredient = Ingredient(key=key, name=name, category=category, default_unit=unit)
        session.add(ingredient)
        session.flush()
    return ingredient


def seed_demo_data() -> dict[str, int]:
    with SessionLocal() as session:  # type: Session
        tomorrow = date.today() + timedelta(days=1)

        # 工作区与站点（固定 ID：前端与接口契约使用 demo-workspace / demo-site / demo-lunch）
        workspace = session.get(Workspace, "demo-workspace")
        if workspace is None:
            workspace = Workspace(id="demo-workspace", name="示例机关食堂", kind="organization")
            session.add(workspace)
            session.flush()

        site = session.get(Site, "demo-site")
        if site is None:
            site = Site(
                id="demo-site", workspace_id=workspace.id, name="总部食堂", service_capacity=200
            )
            session.add(site)
            session.flush()

        # 预置演示管理员（V1 不开放真实登录）
        admin = session.get(User, "demo-admin")
        if admin is None:
            admin = User(
                id="demo-admin",
                email="admin@mealflow.demo",
                password_hash=hash_demo_password("mealflow-demo"),
                display_name="演示管理员",
            )
            session.add(admin)
            session.flush()
        member = session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == admin.id
            )
        )
        if member is None:
            session.add(
                WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="owner")
            )

        # 明日午餐餐次（120 人）
        meal_service = session.get(MealService, "demo-lunch")
        if meal_service is None:
            meal_service = MealService(
                id="demo-lunch",
                site_id=site.id,
                name="午餐",
                service_date=tomorrow,
                expected_diners=120,
                status="draft",
            )
            session.add(meal_service)
            session.flush()
        else:
            meal_service.service_date = tomorrow
            meal_service.expected_diners = 120

        # 演示 Kiosk 终端（绑定总部食堂，令牌哈希落库）
        kiosk = session.scalar(
            select(KioskDevice).where(KioskDevice.device_id == DEMO_KIOSK_DEVICE_ID)
        )
        if kiosk is None:
            kiosk = KioskDevice(device_id=DEMO_KIOSK_DEVICE_ID)
            session.add(kiosk)
        kiosk.workspace_id = workspace.id
        kiosk.site_id = site.id
        kiosk.token_hash = hash_device_token(DEMO_KIOSK_TOKEN)
        kiosk.status = "active"

        # 食材主数据
        ingredients: dict[str, Ingredient] = {}
        for key, name, category, unit in INGREDIENTS:
            ingredients[key] = _get_or_create_ingredient(session, key, name, category, unit)

        # 用餐限制（硬过滤）
        for restriction_type, ingredient_key in RESTRICTIONS:
            exists = session.scalar(
                select(DietaryRestriction).where(
                    DietaryRestriction.workspace_id == workspace.id,
                    DietaryRestriction.type == restriction_type,
                    DietaryRestriction.ingredient_key == ingredient_key,
                )
            )
            if exists is None:
                session.add(
                    DietaryRestriction(
                        workspace_id=workspace.id,
                        type=restriction_type,
                        ingredient_key=ingredient_key,
                    )
                )

        # 库存（含临期番茄）
        for ingredient_key, quantity, unit, expires_after_days in INVENTORY:
            item = session.scalar(
                select(InventoryItem).where(
                    InventoryItem.workspace_id == workspace.id,
                    InventoryItem.ingredient_id == ingredients[ingredient_key].id,
                )
            )
            expires_on = (
                date.today() + timedelta(days=expires_after_days)
                if expires_after_days is not None
                else None
            )
            if item is None:
                session.add(
                    InventoryItem(
                        workspace_id=workspace.id,
                        ingredient_id=ingredients[ingredient_key].id,
                        quantity=quantity,
                        unit=unit,
                        expires_on=expires_on,
                    )
                )
            else:
                item.quantity = quantity
                item.unit = unit
                item.expires_on = expires_on

        # 菜谱与配方明细（data/seed/recipes.json，可溯源）
        payload = json.loads(RECIPE_SEED_PATH.read_text(encoding="utf-8"))
        recipe_count = 0
        for entry in payload["recipes"]:
            recipe = session.scalar(select(Recipe).where(Recipe.name == entry["name"]))
            if recipe is None:
                recipe = Recipe(name=entry["name"])
                session.add(recipe)
            recipe.servings = entry["servings"]
            recipe.duration_minutes = entry["duration_minutes"]
            recipe.kcal_per_serving = entry["kcal_per_serving"]
            recipe.estimated_cost_cents = entry["estimated_cost_cents"]
            recipe.tags = entry["tags"]
            recipe.allergens = entry["allergens"]
            recipe.steps = entry["steps"]
            recipe.source_name = entry["source_name"]
            recipe.source_url = entry["source_url"] or None
            recipe.license_note = entry["license_note"]
            session.flush()

            session.query(RecipeIngredient).filter(
                RecipeIngredient.recipe_id == recipe.id
            ).delete()
            for item in entry["ingredients"]:
                session.add(
                    RecipeIngredient(
                        recipe_id=recipe.id,
                        ingredient_id=ingredients[item["key"]].id,
                        quantity=Decimal(str(item["quantity"])),
                        unit=item["unit"],
                        optional=item.get("optional", False),
                    )
                )
            recipe_count += 1

        session.commit()
        return {"recipes": recipe_count, "ingredients": len(ingredients)}


def main() -> None:
    counts = seed_demo_data()
    print(f"种子数据完成：{counts['recipes']} 道菜谱，{counts['ingredients']} 种食材。")
    print("演示场景：示例机关食堂 / 总部食堂 / 明日午餐 120 人 / 临期番茄 / 花生过敏硬过滤。")
    print(f"演示 Kiosk 设备 {DEMO_KIOSK_DEVICE_ID} 令牌：{DEMO_KIOSK_TOKEN}（请求头 X-Kiosk-Token）。")


if __name__ == "__main__":
    main()
