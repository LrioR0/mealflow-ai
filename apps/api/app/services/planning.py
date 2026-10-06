"""规则引擎：硬过滤、三方案评分、用量换算、采购缺口。

无副作用、可独立测试（技术开发文档 3.2）。评分公式按技术开发文档 5.1：
score = w1*expiring + w2*preference + w3*time + w4*budget + w5*feedback - repeat_penalty
任一硬约束不满足即淘汰，不能用高分抵消。历史菜单 repeat_penalty 在 V1 取 0。
"""

from dataclasses import dataclass
from decimal import Decimal

from app.schemas.agent import MenuOption, PlanningConstraints
from app.services.context_loader import DishFeedbackStats, PlanningContext, RecipeContext
from app.services.planning_rules import procurement_gap, scale_quantity, violates_allergen

TIME_LIMIT_DEFAULT_MINUTES = 90
DISHES_PER_OPTION = 3
FEEDBACK_NEUTRAL = 0.5
# 样本量达到该值后反馈分量不再向中性值收缩（评分终端设计：低样本只作提示）
FEEDBACK_FULL_CONFIDENCE_SAMPLE = 5

# 厨房常备料不作为冰箱库存或采购缺口,但仍参与过敏原/忌口判断。
PANTRY_STAPLE_KEYS = {
    "scallion",
    "ginger",
    "garlic",
    "dried_chili",
    "doubanjiang",
    "soy_sauce",
    "vinegar",
    "starch",
    "oil",
    "salt",
}


@dataclass(frozen=True)
class StrategyWeights:
    key: str
    title: str
    expiring: float
    preference: float
    time: float
    budget: float
    feedback: float


# 三方案共用文档基线权重，仅按软目标重新分配（合计恒为 1）
STRATEGIES: tuple[StrategyWeights, ...] = (
    StrategyWeights("expiring_first", "临期优先", 0.60, 0.15, 0.10, 0.10, 0.05),
    StrategyWeights("original_first", "原方案优先", 0.25, 0.25, 0.20, 0.25, 0.05),
    StrategyWeights("balanced_first", "综合评估优先", 0.25, 0.25, 0.20, 0.25, 0.05),
    StrategyWeights("dislike_first", "忌口优先", 0.20, 0.40, 0.20, 0.15, 0.05),
)


def build_key_names(context: PlanningContext) -> dict[str, str]:
    """ingredient key → 展示名。"""
    key_names: dict[str, str] = {}
    for line in context.inventory:
        key_names[line.key] = line.name
    for recipe in context.recipes:
        for line in recipe.ingredients:
            key_names.setdefault(line.key, line.name)
    return key_names


def _restriction_label(key: str, restriction_types: dict[str, str]) -> str:
    kind = restriction_types.get(key, "allergy")
    return "过敏原" if kind == "allergy" else "忌口"


def hard_filter(
    recipes: list[RecipeContext],
    excluded_keys: list[str],
    key_names: dict[str, str],
    restriction_types: dict[str, str] | None = None,
) -> tuple[list[RecipeContext], list[tuple[str, str]]]:
    """只把过敏原作为硬约束;普通忌口保留菜谱但由方案警告和忌口优先策略处理。"""
    types = restriction_types or {}
    allergy_keys = {key for key in excluded_keys if types.get(key) == "allergy"}
    kept: list[RecipeContext] = []
    filtered: list[tuple[str, str]] = []
    for recipe in recipes:
        hit_keys = recipe.required_ingredient_keys & allergy_keys
        if hit_keys:
            detail = "、".join(
                f"{_restriction_label(key, types)}：{key_names.get(key, key)}"
                for key in sorted(hit_keys)
            )
            filtered.append((recipe.name, f"命中家庭档案限制（{detail}）"))
            continue
        excluded_names = [key_names[key] for key in allergy_keys if key in key_names]
        if violates_allergen(recipe.allergens, excluded_names):
            hit_names = "、".join(
                name for name in excluded_names if name in recipe.allergens
            )
            filtered.append((recipe.name, f"过敏原命中（{hit_names}）"))
            continue
        kept.append(recipe)
    return kept, filtered


def feedback_component(stats: DishFeedbackStats | None) -> float:
    """1–5 分映射到 0–1；样本不足时向中性值收缩，低样本不会大幅改变排序。"""
    if stats is None or stats.sample_count <= 0:
        return FEEDBACK_NEUTRAL
    normalized = (stats.avg_rating - 1.0) / 4.0
    confidence = min(stats.sample_count / FEEDBACK_FULL_CONFIDENCE_SAMPLE, 1.0)
    return round(FEEDBACK_NEUTRAL + (normalized - FEEDBACK_NEUTRAL) * confidence, 3)


def component_scores(
    recipe: RecipeContext,
    expiring_keys: set[str],
    style_tags: list[str],
    time_limit_minutes: int,
    cost_cap_cents: int,
    dish_feedback: dict[str, DishFeedbackStats] | None = None,
) -> dict[str, float]:
    required = [line for line in recipe.ingredients if not line.optional]
    if required:
        expiring = sum(1 for line in required if line.key in expiring_keys) / len(required)
    else:
        expiring = 0.0
    if style_tags:
        preference = len(set(recipe.tags) & set(style_tags)) / len(style_tags)
    else:
        preference = 0.5  # 未声明口味偏好时取中性值
    overtime = max(0, recipe.duration_minutes - time_limit_minutes)
    time_fit = max(0.0, 1.0 - overtime / max(time_limit_minutes, 1))
    budget_fit = max(0.0, 1.0 - (recipe.estimated_cost_cents or 0) / max(cost_cap_cents, 1))
    return {
        "expiring": round(expiring, 3),
        "preference": round(preference, 3),
        "time": round(time_fit, 3),
        "budget": round(budget_fit, 3),
        "feedback": feedback_component((dish_feedback or {}).get(recipe.name)),
    }


def score_candidates(
    kept: list[RecipeContext],
    context: PlanningContext,
    constraints: PlanningConstraints,
    expiring_keys: set[str],
) -> list[tuple[RecipeContext, dict[str, float]]]:
    style_tags = constraints.dietary_style
    time_limit = constraints.time_limit_minutes or TIME_LIMIT_DEFAULT_MINUTES
    cost_cap = max((recipe.estimated_cost_cents or 0 for recipe in kept), default=0) or 1
    return [
        (
            recipe,
            component_scores(
                recipe,
                expiring_keys,
                style_tags,
                time_limit,
                cost_cap,
                context.dish_feedback,
            ),
        )
        for recipe in kept
    ]


def weighted_score(weights: StrategyWeights, breakdown: dict[str, float]) -> float:
    return round(
        weights.expiring * breakdown["expiring"]
        + weights.preference * breakdown["preference"]
        + weights.time * breakdown["time"]
        + weights.budget * breakdown["budget"]
        + weights.feedback * breakdown["feedback"],
        3,
    )


def _normalize_dish_name(value: str) -> str:
    return value.strip().replace("面条", "面").replace(" ", "")


def _matches_preferred_dish(recipe: RecipeContext, preferred_dishes: list[str]) -> bool:
    recipe_name = _normalize_dish_name(recipe.name)
    return any(
        (requested := _normalize_dish_name(value))
        and (requested in recipe_name or recipe_name in requested)
        for value in preferred_dishes
    )


def choose_top(
    scored: list[tuple[RecipeContext, dict[str, float]]],
    weights: StrategyWeights,
    context: PlanningContext,
    preferred_dishes: list[str] | None = None,
) -> list[RecipeContext]:
    if weights.key == "original_first":
        # 原方案优先:保留菜谱库经过硬约束过滤后的原始顺序,
        # 不让临期、成本或历史反馈重新打乱标准菜谱顺序。
        ordered = list(scored)
    elif weights.key == "dislike_first":
        dislike_keys = {
            constraint.ingredient_key
            for constraint in context.member_constraints
            if constraint.kind == "restriction"
            and constraint.level == "warn"
            and constraint.ingredient_key
        }
        ordered = sorted(
            scored,
            key=lambda item: (
                len(item[0].required_ingredient_keys & dislike_keys),
                -weighted_score(weights, item[1]),
                item[0].name,
            ),
        )
    else:
        ordered = sorted(
            scored, key=lambda item: (-weighted_score(weights, item[1]), item[0].name)
        )
    preferences = preferred_dishes or []
    preferred = [recipe for recipe, _ in ordered if _matches_preferred_dish(recipe, preferences)]
    remaining = [recipe for recipe, _ in ordered if recipe not in preferred]
    return (preferred + remaining)[:DISHES_PER_OPTION]


def compute_requirements(chosen: list[RecipeContext], diners: int) -> dict[str, Decimal]:
    """按人数换算所有选中菜谱的必需食材总需求量。"""
    requirements: dict[str, Decimal] = {}
    for recipe in chosen:
        for line in recipe.ingredients:
            if line.optional:
                continue
            scaled = scale_quantity(line.quantity, recipe.servings, diners)
            requirements[line.key] = requirements.get(line.key, Decimal("0")) + scaled
    return requirements


def procurement_lines(
    requirements: dict[str, Decimal], context: PlanningContext, key_names: dict[str, str]
) -> list[dict]:
    lines: list[dict] = []
    for key in sorted(requirements):
        if key in PANTRY_STAPLE_KEYS:
            continue
        required = requirements[key]
        available = context.available_for(key)
        gap = procurement_gap(required, available)
        if gap <= 0:
            continue
        unit = context.inventory_unit(key) or ""
        lines.append(
            {
                "ingredient": key_names.get(key, key),
                "missing_quantity": f"{gap.quantize(Decimal('0.01'))}{unit}",
                "required": str(required.quantize(Decimal("0.01"))),
                "available": str(available.quantize(Decimal("0.01"))),
                "unit": unit,
            }
        )
    return lines


def estimate_totals(chosen: list[RecipeContext], diners: int) -> tuple[int, int | None]:
    """返回 (总成本分, 人均热量 kcal)。"""
    total_cost_cents = 0
    total_kcal = 0
    for recipe in chosen:
        total_cost_cents += (recipe.estimated_cost_cents or 0) * diners
        total_kcal += recipe.kcal_per_serving or 0
    return total_cost_cents, (total_kcal or None)


def build_option(
    weights: StrategyWeights,
    scored: list[tuple[RecipeContext, dict[str, float]]],
    context: PlanningContext,
    constraints: PlanningConstraints,
    filtered_out: list[tuple[str, str]],
    key_names: dict[str, str],
) -> MenuOption:
    diners = constraints.expected_diners or context.expected_diners
    chosen = choose_top(scored, weights, context, constraints.preferred_dishes)

    requirements = compute_requirements(chosen, diners)
    procurement = procurement_lines(requirements, context, key_names)
    pantry_names = sorted(
        {
            key_names[line.key]
            for recipe in chosen
            for line in recipe.ingredients
            if line.key in PANTRY_STAPLE_KEYS and line.key in key_names
        }
    )
    pantry_notes = (
        [f"本方案还会用到：{'、'.join(pantry_names)}。请确认厨房常备料是否齐全。"]
        if pantry_names
        else []
    )
    total_cost_cents, total_kcal = estimate_totals(chosen, diners)

    breakdown = {
        part: round(sum(scores[part] for _, scores in scored[: len(chosen)]) / len(chosen), 3)
        for part in ("expiring", "preference", "time", "budget", "feedback")
    }

    reasons: list[str] = []
    expiring_used = sorted(
        {
            key_names[line.key]
            for recipe in chosen
            for line in recipe.ingredients
            if not line.optional and line.key in context.expiring_keys(context.service_date)
        }
    )
    if expiring_used:
        reasons.append(f"优先利用临期食材（{'、'.join(expiring_used)}）")
    matched_preferences = [
        recipe.name
        for recipe in chosen
        if _matches_preferred_dish(recipe, constraints.preferred_dishes)
    ]
    if matched_preferences:
        reasons.append(f"响应点名菜品（{'、'.join(matched_preferences)}）")
    for style in constraints.dietary_style:
        if any(style in recipe.tags for recipe in chosen):
            reasons.append(f"命中“{style}”偏好")
    if filtered_out:
        reasons.append(
            "已按家庭档案的用餐限制排除（非本次输入）："
            + "；".join(f"{name}（{reason}）" for name, reason in filtered_out[:3])
        )
    if weights.key == "original_first":
        reasons.append("按菜谱原版做法与标准配比推荐")
    if weights.key == "balanced_first":
        reasons.append("综合评估临期、口味、时间、预算与历史反馈")
    if weights.key == "dislike_first":
        reasons.append("优先避开家庭成员的长期忌口，过敏原始终为红线")

    # 反馈回流（评分终端设计 §5）：只影响软评分并给出可解释提示，不突破硬约束
    penalized: list[str] = []
    favored: list[str] = []
    for recipe in chosen:
        stats = context.dish_feedback.get(recipe.name)
        if stats is None or stats.sample_count <= 0:
            continue
        if stats.avg_rating < 3.5:
            reason_tags = "、".join(stats.top_tags) or "整体"
            penalized.append(
                f"{recipe.name}（上次 {stats.avg_rating:.1f} 分，{reason_tags}反馈较多）"
            )
        elif stats.avg_rating >= 4.5:
            favored.append(f"{recipe.name}（上次 {stats.avg_rating:.1f} 分）")
    if penalized:
        reasons.append("反馈回流：上次评分偏低的菜品已降低权重——" + "；".join(penalized))
    if favored:
        reasons.append("反馈回流：上次评分较高，满意度加权保留——" + "、".join(favored))

    warnings: list[str] = []
    if constraints.preferred_dishes and not matched_preferences:
        warnings.append(
            "点名菜品未在可用菜谱中命中，或因家庭饮食限制被排除："
            + "、".join(constraints.preferred_dishes)
        )
    budget_cents = constraints.budget_limit_cents
    if budget_cents and total_cost_cents > budget_cents:
        warnings.append(
            f"预计成本 {total_cost_cents / 100:.0f} 元超过预算 "
            f"{budget_cents / 100:.0f} 元，需调整方案"
        )

    return MenuOption(
        strategy=weights.key,
        title=weights.title,
        items=[
            {
                "name": recipe.name,
                "servings": diners,
                "kcal_per_serving": recipe.kcal_per_serving,
            }
            for recipe in chosen
        ],
        estimated_cost_cents=total_cost_cents,
        estimated_kcal_per_serving=total_kcal,
        score_breakdown={
            **breakdown,
            "total": round(
                sum(weighted_score(weights, scores) for _, scores in scored[: len(chosen)])
                / len(chosen),
                3,
            ),
        },
        procurement_list=procurement,
        pantry_notes=pantry_notes,
        reasons=reasons,
        warnings=warnings,
    )


def build_all_options(
    scored: list[tuple[RecipeContext, dict[str, float]]],
    context: PlanningContext,
    constraints: PlanningConstraints,
    filtered_out: list[tuple[str, str]],
    key_names: dict[str, str],
) -> list[MenuOption]:
    return [
        build_option(weights, scored, context, constraints, filtered_out, key_names)
        for weights in STRATEGIES
    ]
