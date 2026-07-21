from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.domain.rules import evaluate_market_rules, rules_for_profile
from app.integrations.binance import CandleData
from app.main import create_app
from app.models import AlertRule
from app.services.alerts import AlertService
from app.services.ingestion import IngestionService


@pytest.fixture
def api_context(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    now = datetime.now(UTC).replace(microsecond=0)
    candles = [_api_candle(index, now - timedelta(minutes=15 * 100)) for index in range(100)]
    IngestionService(factory).ingest_asset("BTCBRL", candles, calculated_at=now)
    rule_events = evaluate_market_rules(
        {"volatility_24h_pct": 4.5}, rules_for_profile("moderate")
    )
    alert_result = AlertService(factory).sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=rule_events,
        evaluated_codes={"volatility_24h"},
        observed_at=now,
    )
    settings = Settings(
        _env_file=None,
        database_url=test_database_url,
        operator_password="correct-horse",
        session_secret="a-test-secret-that-is-long-enough",
    )
    app = create_app(settings=settings, session_factory=factory)
    with TestClient(app) as client:
        yield client, factory, alert_result.alert_ids[0]
    engine.dispose()


def test_public_market_endpoints_return_persisted_data(api_context):
    client, _, _ = api_context

    health = client.get("/api/health")
    assets = client.get("/api/assets")
    market = client.get("/api/market")
    candles = client.get("/api/assets/BTCBRL/candles", params={"period": "24h", "limit": 10})
    alerts = client.get("/api/alerts")

    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert len(assets.json()) == 4
    assert {item["symbol"] for item in market.json()} == {
        "BTCBRL",
        "ETHBRL",
        "SOLBRL",
        "USDTBRL",
    }
    assert len(candles.json()) == 10
    assert candles.json()[-1]["close"] == pytest.approx(109.9)
    assert alerts.json()[0]["status"] == "new"


def test_operator_login_protects_mutations_and_logout(api_context):
    client, factory, alert_id = api_context
    with factory() as session:
        rule_id = session.scalar(
            select(AlertRule.id).where(AlertRule.code == "volatility_24h")
        )

    unauthorized = client.put(
        "/api/portfolio/positions/BTCBRL",
        json={"quantity": 0.01, "cost_basis_brl": 100.0},
    )
    wrong_login = client.post("/api/auth/login", json={"password": "wrong"})
    login = client.post("/api/auth/login", json={"password": "correct-horse"})

    assert unauthorized.status_code == 401
    assert wrong_login.status_code == 401
    assert login.status_code == 200
    assert client.get("/api/auth/session").json()["authenticated"] is True

    position = client.put(
        "/api/portfolio/positions/BTCBRL",
        json={"quantity": 0.01, "cost_basis_brl": 100.0},
    )
    portfolio = client.get("/api/portfolio")
    rule = client.patch(f"/api/rules/{rule_id}", json={"threshold": 4.25})
    alert = client.patch(f"/api/alerts/{alert_id}", json={"status": "acknowledged"})

    assert position.status_code == 200
    assert portfolio.json()["total_value_brl"] == pytest.approx(1.099)
    assert rule.json()["threshold"] == pytest.approx(4.25)
    assert alert.json()["status"] == "acknowledged"

    assert client.post("/api/auth/logout").status_code == 200
    assert client.patch(f"/api/rules/{rule_id}", json={"enabled": False}).status_code == 401


def _api_candle(index: int, start: datetime) -> CandleData:
    opened_at = start + timedelta(minutes=15 * index)
    close = Decimal("100") + Decimal(index) / Decimal("10")
    return CandleData(
        symbol="BTCBRL",
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=15) - timedelta(milliseconds=1),
        open_price=close - Decimal("0.1"),
        high_price=close + Decimal("0.2"),
        low_price=close - Decimal("0.2"),
        close_price=close,
        volume=Decimal("10"),
        trade_count=20,
    )
