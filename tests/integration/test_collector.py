from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.collector import COLLECTOR_LOCK_KEY, collect_once, completed_candle_boundary
from app.config import Settings
from app.integrations.binance import CandleData
from app.models import Alert, AlertEvent, AlertRule, Asset, Candle, IngestionRun, PortfolioPosition


class FakeMarketClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, datetime, datetime]] = []

    def fetch_candles(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str = "15m",
    ) -> list[CandleData]:
        self.requests.append((symbol, start, end))
        opened_at = end - timedelta(minutes=15)
        return [
            CandleData(
                symbol=symbol,
                opened_at=opened_at,
                closed_at=end - timedelta(milliseconds=1),
                open_price=Decimal("100"),
                high_price=Decimal("102"),
                low_price=Decimal("99"),
                close_price=Decimal("101"),
                volume=Decimal("10"),
                trade_count=20,
            )
        ]


@pytest.fixture
def collector_context(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url=test_database_url,
        operator_password="test",
        session_secret="test-secret-for-collector",
    )
    yield factory, settings
    engine.dispose()


def test_completed_boundary_ignores_the_current_unfinished_candle():
    now = datetime(2026, 7, 20, 12, 7, 33, tzinfo=UTC)

    assert completed_candle_boundary(now) == datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_collector_updates_four_assets_without_duplicate_candles(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    first = collect_once(settings, session_factory=factory, market_client=client, now=now)
    second = collect_once(settings, session_factory=factory, market_client=client, now=now)

    with factory() as session:
        candle_count = session.scalar(select(func.count()).select_from(Candle))
        run_count = session.scalar(select(func.count()).select_from(IngestionRun))
    assert first.lock_acquired is True
    assert first.assets_processed == 4
    assert second.assets_processed == 4
    assert candle_count == 4
    assert run_count == 8
    assert all(request[2].minute == 0 for request in client.requests)
    assert all(request[1] == request[2] - timedelta(days=7) for request in client.requests[:4])


def test_collector_evaluates_market_and_portfolio_alerts(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    with factory.begin() as session:
        rules = list(session.scalars(select(AlertRule)))
        for rule in rules:
            rule.enabled = rule.code in {"stale_market_data", "portfolio_concentration"}
            if rule.code == "stale_market_data":
                rule.threshold = Decimal("0")
            if rule.code == "portfolio_concentration":
                rule.threshold = Decimal("50")
        btc_id = session.scalar(select(Asset.id).where(Asset.symbol == "BTCBRL"))
        session.add(PortfolioPosition(asset_id=btc_id, quantity=Decimal("0.01")))

    result = collect_once(settings, session_factory=factory, market_client=client, now=now)

    with factory() as session:
        alerts = list(session.scalars(select(Alert).order_by(Alert.id)))
        event_count = session.scalar(select(func.count()).select_from(AlertEvent))
    assert result.errors == ()
    assert len(alerts) == 5
    assert event_count == 5
    assert {alert.dedupe_key for alert in alerts} == {
        "moderate:stale_market_data:BTCBRL",
        "moderate:stale_market_data:ETHBRL",
        "moderate:stale_market_data:SOLBRL",
        "moderate:stale_market_data:USDTBRL",
        "moderate:portfolio_concentration:portfolio",
    }


def test_collector_skips_cycle_when_another_instance_holds_the_lock(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()

    with factory() as lock_session:
        acquired = lock_session.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": COLLECTOR_LOCK_KEY},
        )
        assert acquired is True
        try:
            result = collect_once(settings, session_factory=factory, market_client=client)
        finally:
            lock_session.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": COLLECTOR_LOCK_KEY},
            )

    assert result.lock_acquired is False
    assert client.requests == []
