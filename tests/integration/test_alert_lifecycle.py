from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.domain.rules import evaluate_market_rules, rules_for_profile
from app.models import Alert, AlertEvent
from app.services.alerts import AlertService, InvalidAlertTransition


@pytest.fixture
def alert_context(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_alert_is_deduplicated_resolved_and_reopened(alert_context):
    service = AlertService(alert_context)
    rule_set = rules_for_profile("moderate")
    base_time = datetime(2026, 7, 20, 12, tzinfo=UTC)
    first_event = evaluate_market_rules({"volatility_24h_pct": 4.5}, rule_set)

    service.sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=first_event,
        evaluated_codes={"volatility_24h"},
        observed_at=base_time,
    )
    second_event = evaluate_market_rules({"volatility_24h_pct": 5.0}, rule_set)
    service.sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=second_event,
        evaluated_codes={"volatility_24h"},
        observed_at=base_time + timedelta(minutes=15),
    )

    with alert_context() as session:
        alert = session.scalars(select(Alert)).one()
        alert_id = alert.id
        assert alert.status == "new"
        assert alert.condition_active is True
        assert float(alert.observed_value) == 5.0
        assert [event.action for event in alert.events] == ["triggered", "aggravated"]

    service.transition(alert_id, "acknowledged", actor="operator")
    service.sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=[],
        evaluated_codes={"volatility_24h"},
        observed_at=base_time + timedelta(minutes=30),
    )
    service.sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=first_event,
        evaluated_codes={"volatility_24h"},
        observed_at=base_time + timedelta(minutes=45),
    )

    with alert_context() as session:
        alert = session.get(Alert, alert_id)
        assert alert is not None
        assert alert.status == "new"
        assert alert.condition_active is True
        assert session.scalar(select(func.count()).select_from(Alert)) == 1
        actions = session.scalars(
            select(AlertEvent.action).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.id)
        ).all()
    assert actions == ["triggered", "aggravated", "acknowledged", "resolved", "reopened"]


def test_invalid_manual_transition_does_not_change_alert(alert_context):
    service = AlertService(alert_context)
    events = evaluate_market_rules({"volatility_24h_pct": 4.5}, rules_for_profile("moderate"))
    result = service.sync(
        profile="moderate",
        scope="market",
        asset_symbol="BTCBRL",
        events=events,
        evaluated_codes={"volatility_24h"},
        observed_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
    )
    service.transition(result.alert_ids[0], "resolved", actor="operator")

    with pytest.raises(InvalidAlertTransition):
        service.transition(result.alert_ids[0], "acknowledged", actor="operator")

    with alert_context() as session:
        assert session.get(Alert, result.alert_ids[0]).status == "resolved"
