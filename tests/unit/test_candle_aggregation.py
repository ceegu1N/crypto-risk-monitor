from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.api.routes import _aggregate_candles


def test_aggregate_candles_preserves_ohlcv_in_time_order():
    start = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    rows = [
        _candle(start, "100", "103", "99", "102", "10"),
        _candle(start + timedelta(minutes=15), "102", "105", "101", "104", "20"),
        _candle(start + timedelta(minutes=30), "104", "106", "103", "105", "30"),
        _candle(start + timedelta(minutes=60), "105", "108", "104", "107", "40"),
    ]

    result = _aggregate_candles(rows, 60)

    assert len(result) == 2
    assert result[0]["opened_at"] == start
    assert result[0]["open"] == Decimal("100")
    assert result[0]["high"] == Decimal("106")
    assert result[0]["low"] == Decimal("99")
    assert result[0]["close"] == Decimal("105")
    assert result[0]["volume"] == Decimal("60")
    assert result[1]["close"] == Decimal("107")


def _candle(start, open_price, high, low, close, volume):
    return SimpleNamespace(
        opened_at=start,
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal(volume),
    )
