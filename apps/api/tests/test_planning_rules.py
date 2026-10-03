from decimal import Decimal

import pytest

from app.services.planning_rules import procurement_gap, scale_quantity, violates_allergen


def test_scale_quantity() -> None:
    assert scale_quantity(Decimal("2.5"), 10, 120) == Decimal("30.000")


def test_procurement_gap_never_negative() -> None:
    assert procurement_gap(Decimal("5"), Decimal("8")) == Decimal("0")


def test_allergen_is_hard_constraint() -> None:
    assert violates_allergen(["花生", "大豆"], ["花生"])


def test_rejects_invalid_servings() -> None:
    with pytest.raises(ValueError):
        scale_quantity(Decimal("1"), 0, 120)
