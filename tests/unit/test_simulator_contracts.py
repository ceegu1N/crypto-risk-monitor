from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.schemas import TradeRequest, TradeSide


def test_trade_request_accepts_a_buy_by_brl_amount():
    request = TradeRequest(side=TradeSide.BUY, notional_brl=Decimal("250"))

    assert request.side is TradeSide.BUY
    assert request.notional_brl == Decimal("250")
    assert request.quantity is None


def test_trade_request_accepts_a_sell_by_quantity():
    request = TradeRequest(side=TradeSide.SELL, quantity=Decimal("0.01"))

    assert request.side is TradeSide.SELL
    assert request.quantity == Decimal("0.01")


@pytest.mark.parametrize(
    "payload",
    [
        {"side": "buy"},
        {"side": "buy", "quantity": "0.01", "notional_brl": "250"},
        {"side": "sell", "notional_brl": "250"},
        {"side": "sell", "quantity": "0"},
        {"side": "buy", "notional_brl": "-1"},
    ],
)
def test_trade_request_rejects_ambiguous_or_non_positive_orders(payload):
    with pytest.raises(ValidationError):
        TradeRequest.model_validate(payload)
