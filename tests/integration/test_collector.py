from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.collector import (
    COLLECTOR_LOCK_KEY,
    collect_once,
    completed_candle_boundary,
    rebuild_quote_volume,
)
from app.config import Settings
from app.integrations.binance import CandleData
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    AppSetting,
    Asset,
    Candle,
    IngestionRun,
    PortfolioPosition,
    RiskSnapshot,
)


class FakeMarketClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, datetime, datetime]] = []
        self.fail_symbols: set[str] = set()

    def fetch_candles(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str = "15m",
    ) -> list[CandleData]:
        self.requests.append((symbol, start, end))
        if symbol in self.fail_symbols:
            raise RuntimeError(f"upstream unavailable for {symbol}")
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


def test_collector_updates_seven_assets_without_duplicate_candles(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    first = collect_once(settings, session_factory=factory, market_client=client, now=now)
    second = collect_once(settings, session_factory=factory, market_client=client, now=now)

    with factory() as session:
        candle_count = session.scalar(select(func.count()).select_from(Candle))
        snapshot_count = session.scalar(select(func.count()).select_from(RiskSnapshot))
        run_count = session.scalar(select(func.count()).select_from(IngestionRun))
    assert first.lock_acquired is True
    assert first.assets_processed == 7
    assert second.assets_processed == 7
    assert candle_count == 7
    assert snapshot_count == 7
    assert run_count == 14
    assert all(request[2].minute == 0 for request in client.requests)
    assert all(request[1] == request[2] - timedelta(days=90) for request in client.requests[:7])


def test_quote_volume_backfill_rewrites_history_for_all_assets(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    result = rebuild_quote_volume(
        settings,
        days=30,
        session_factory=factory,
        market_client=client,
        now=now,
    )

    with factory() as session:
        candle_count = session.scalar(select(func.count()).select_from(Candle))
        volume = session.scalar(select(Candle.volume).order_by(Candle.id).limit(1))
        run_count = session.scalar(select(func.count()).select_from(IngestionRun))

    assert result.lock_acquired is True
    assert result.assets_processed == 7
    assert result.candles_processed == 7
    assert candle_count == 7
    assert volume == Decimal("10")
    assert run_count == 7
    assert all(request[1] == request[2] - timedelta(days=30) for request in client.requests)


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
    assert len(alerts) == 8
    assert event_count == 8
    assert {alert.dedupe_key for alert in alerts} == {
        "moderate:stale_market_data:BTCBRL",
        "moderate:stale_market_data:ETHBRL",
        "moderate:stale_market_data:SOLBRL",
        "moderate:stale_market_data:USDTBRL",
        "moderate:stale_market_data:ADABRL",
        "moderate:stale_market_data:PEPEBRL",
        "moderate:stale_market_data:NEARBRL",
        "moderate:portfolio_concentration:portfolio",
    }


def test_fetch_failure_is_recorded_and_increases_effective_staleness(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    first_now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    with factory.begin() as session:
        rules = list(session.scalars(select(AlertRule)))
        for rule in rules:
            rule.enabled = rule.profile == "moderate" and rule.code == "stale_market_data"
            if rule.enabled:
                rule.threshold = Decimal("60")

    first = collect_once(
        settings,
        session_factory=factory,
        market_client=client,
        now=first_now,
    )
    client.fail_symbols.add("BTCBRL")
    second = collect_once(
        settings,
        session_factory=factory,
        market_client=client,
        now=first_now + timedelta(hours=2),
    )

    with factory() as session:
        failed_runs = list(
            session.scalars(select(IngestionRun).where(IngestionRun.status == "failed"))
        )
        active_alerts = list(session.scalars(select(Alert).where(Alert.condition_active.is_(True))))

    assert first.errors == ()
    assert second.assets_processed == 6
    assert len(failed_runs) == 1
    assert "BTCBRL" in (failed_runs[0].error_message or "")
    assert {alert.dedupe_key for alert in active_alerts} == {"moderate:stale_market_data:BTCBRL"}


def test_ingestion_failure_creates_only_one_audit_run(collector_context):
    factory, settings = collector_context

    class InvalidBatchClient(FakeMarketClient):
        def fetch_candles(self, symbol, **kwargs):
            rows = super().fetch_candles(symbol, **kwargs)
            if symbol == "BTCBRL":
                candle = rows[0]
                rows[0] = CandleData(
                    symbol="ETHBRL",
                    opened_at=candle.opened_at,
                    closed_at=candle.closed_at,
                    open_price=candle.open_price,
                    high_price=candle.high_price,
                    low_price=candle.low_price,
                    close_price=candle.close_price,
                    volume=candle.volume,
                    trade_count=candle.trade_count,
                )
            return rows

    result = collect_once(
        settings,
        session_factory=factory,
        market_client=InvalidBatchClient(),
        now=datetime(2026, 7, 20, 12, 7, tzinfo=UTC),
    )

    with factory() as session:
        runs = list(session.scalars(select(IngestionRun).order_by(IngestionRun.id)))

    assert result.assets_processed == 6
    assert len(result.errors) == 1
    assert len(runs) == 7
    assert [run.status for run in runs].count("failed") == 1


def test_disabling_a_rule_clears_its_active_alerts(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()
    first_now = datetime(2026, 7, 20, 12, 7, tzinfo=UTC)

    with factory.begin() as session:
        rules = list(session.scalars(select(AlertRule)))
        for rule in rules:
            rule.enabled = rule.profile == "moderate" and rule.code == "stale_market_data"
            if rule.enabled:
                rule.threshold = Decimal("0")

    collect_once(settings, session_factory=factory, market_client=client, now=first_now)

    with factory.begin() as session:
        rule = session.scalar(
            select(AlertRule).where(
                AlertRule.profile == "moderate",
                AlertRule.code == "stale_market_data",
            )
        )
        assert rule is not None
        rule.enabled = False

    collect_once(
        settings,
        session_factory=factory,
        market_client=client,
        now=first_now + timedelta(minutes=15),
    )

    with factory() as session:
        alerts = list(session.scalars(select(Alert).order_by(Alert.id)))
        actions = list(session.scalars(select(AlertEvent.action).order_by(AlertEvent.id)))

    assert len(alerts) == 7
    assert all(alert.status == "resolved" for alert in alerts)
    assert all(alert.condition_active is False for alert in alerts)
    assert actions.count("disabled") == 7


def test_collector_uses_the_profile_persisted_by_the_web(collector_context):
    factory, settings = collector_context
    client = FakeMarketClient()

    with factory.begin() as session:
        session.add(AppSetting(key="active_risk_profile", value="conservative"))
        rules = list(session.scalars(select(AlertRule)))
        for rule in rules:
            rule.enabled = rule.profile == "conservative" and rule.code == "stale_market_data"
            if rule.enabled:
                rule.threshold = Decimal("0")

    collect_once(
        settings,
        session_factory=factory,
        market_client=client,
        now=datetime(2026, 7, 20, 12, 7, tzinfo=UTC),
    )

    with factory() as session:
        keys = set(session.scalars(select(Alert.dedupe_key)))

    assert keys == {
        "conservative:stale_market_data:BTCBRL",
        "conservative:stale_market_data:ETHBRL",
        "conservative:stale_market_data:SOLBRL",
        "conservative:stale_market_data:USDTBRL",
        "conservative:stale_market_data:ADABRL",
        "conservative:stale_market_data:PEPEBRL",
        "conservative:stale_market_data:NEARBRL",
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
