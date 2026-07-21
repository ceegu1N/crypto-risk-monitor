from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

from app.integrations.binance import CandleData
from app.services.ingestion import _upsert_candles


def make_candle(index: int) -> CandleData:
    opened_at = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=15 * index)
    close = Decimal("100") + Decimal(index) / Decimal("10")
    return CandleData(
        symbol="BTCBRL",
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=15) - timedelta(milliseconds=1),
        open_price=close - Decimal("0.1"),
        high_price=close + Decimal("0.2"),
        low_price=close - Decimal("0.2"),
        close_price=close,
        volume=Decimal("10") + index,
        trade_count=20 + index,
    )


def test_upsert_candles_splits_large_batches_before_postgres_parameter_limit():
    session = Mock()

    _upsert_candles(session, asset_id=1, candles=[make_candle(index) for index in range(5001)])

    assert session.execute.call_count == 2
