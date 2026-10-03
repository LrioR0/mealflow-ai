from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class IngredientRequirement:
    ingredient: str
    quantity: Decimal
    unit: str


def scale_quantity(base_quantity: Decimal, base_servings: int, target_servings: int) -> Decimal:
    if base_servings <= 0 or target_servings <= 0:
        raise ValueError("servings must be positive")
    return (base_quantity * Decimal(target_servings) / Decimal(base_servings)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )


def procurement_gap(required: Decimal, available: Decimal) -> Decimal:
    return max(Decimal("0"), required - available)


def violates_allergen(recipe_allergens: list[str], excluded: list[str]) -> bool:
    return bool(set(recipe_allergens) & set(excluded))
