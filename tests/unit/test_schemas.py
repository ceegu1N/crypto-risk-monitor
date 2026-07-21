from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.schemas import PositionUpsert, RuleUpdate


def test_position_rejects_more_decimal_places_than_the_database_supports():
    with pytest.raises(ValidationError):
        PositionUpsert(quantity=Decimal("0.0000000000001"))


def test_rule_threshold_rejects_values_larger_than_the_database_column():
    with pytest.raises(ValidationError):
        RuleUpdate(threshold=Decimal("1234567890123.12345678"))


def test_numeric_payloads_accept_values_within_database_precision():
    position = PositionUpsert(
        quantity=Decimal("0.000000000001"),
        cost_basis_brl=Decimal("123456789012345678.123456789012"),
    )
    rule = RuleUpdate(threshold=Decimal("123456789012.12345678"))

    assert position.quantity == Decimal("0.000000000001")
    assert rule.threshold == Decimal("123456789012.12345678")
