from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.integrations.binance import CandleData
from app.models import Candle, IngestionRun, RiskSnapshot
from app.services.ingestion import IngestionError, IngestionService


def make_candle(index: int, *, valid: bool = True) -> CandleData:
    opened_at = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=15 * index)
    close = Decimal("100") + Decimal(index) / Decimal("10")
    return CandleData(
        symbol="BTCBRL",
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=15) - timedelta(milliseconds=1),
        open_price=close - Decimal("0.1"),
        high_price=close + Decimal("0.2") if valid else close - Decimal("1"),
        low_price=close - Decimal("0.2"),
        close_price=close,
        volume=Decimal("10") + index,
        trade_count=20 + index,
    )


@pytest.fixture
def ingestion_context(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def test_ingesting_the_same_batch_twice_is_idempotent(ingestion_context):
    engine, factory = ingestion_context
    candles = [make_candle(index) for index in range(100)]
    calculated_at = candles[-1].closed_at + timedelta(minutes=1)
    service = IngestionService(factory)

    first = service.ingest_asset("BTCBRL", candles, calculated_at=calculated_at)
    second = service.ingest_asset("BTCBRL", candles, calculated_at=calculated_at)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Candle)) == 100
        assert session.scalar(select(func.count()).select_from(RiskSnapshot)) == 1
        runs = session.scalars(select(IngestionRun).order_by(IngestionRun.id)).all()
        latest_snapshot = session.scalars(
            select(RiskSnapshot).order_by(RiskSnapshot.id.desc()).limit(1)
        ).one()
    assert first.candles_processed == 100
    assert second.candles_processed == 100
    assert first.risk_snapshot_id == second.risk_snapshot_id
    assert [run.status for run in runs] == ["success", "success"]
    assert [run.source for run in runs] == ["binance:BTCBRL", "binance:BTCBRL"]
    assert latest_snapshot.return_1h_pct is not None
    assert latest_snapshot.return_24h_pct is not None
    assert engine is not None


def test_invalid_batch_rolls_back_market_data_and_records_failure(ingestion_context):
    _, factory = ingestion_context
    service = IngestionService(factory)
    first = make_candle(0)
    service.ingest_asset("BTCBRL", [first], calculated_at=first.closed_at)

    with pytest.raises(IngestionError, match="could not ingest BTCBRL"):
        service.ingest_asset(
            "BTCBRL",
            [make_candle(1), make_candle(2, valid=False)],
            calculated_at=make_candle(2).closed_at,
        )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Candle)) == 1
        runs = session.scalars(select(IngestionRun).order_by(IngestionRun.id)).all()
    assert [run.status for run in runs] == ["success", "failed"]
    assert runs[-1].error_message
