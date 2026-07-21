from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.models import AlertRule, Asset


def test_initial_migration_creates_tables_and_seed_data(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)

    expected_tables = {
        "assets",
        "candles",
        "risk_snapshots",
        "alert_rules",
        "alerts",
        "alert_events",
        "portfolio_positions",
        "ingestion_runs",
        "app_settings",
    }
    assert expected_tables <= set(inspect(engine).get_table_names())

    with engine.connect() as connection:
        asset_count = connection.scalar(text(f"SELECT count(*) FROM {Asset.__tablename__}"))
        rule_count = connection.scalar(text(f"SELECT count(*) FROM {AlertRule.__tablename__}"))
        rules_by_profile = {
            profile: count
            for profile, count in connection.execute(
                text("SELECT profile, count(*) FROM alert_rules GROUP BY profile ORDER BY profile")
            )
        }
        portfolio_labels = {
            code: label
            for code, label in connection.execute(
                text(
                    "SELECT code, label FROM alert_rules "
                    "WHERE profile = 'moderate' AND code IN "
                    "('portfolio_concentration', 'volatile_asset_share')"
                )
            )
        }
    assert asset_count == 4
    assert rule_count == 24
    assert rules_by_profile == {
        "aggressive": 6,
        "conservative": 6,
        "custom": 6,
        "moderate": 6,
    }
    assert portfolio_labels == {
        "portfolio_concentration": "Concentração do portfólio",
        "volatile_asset_share": "Exposição a ativos voláteis",
    }

    engine.dispose()


@pytest.mark.parametrize(
    (
        "opened_at",
        "closed_at",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "trade_count",
    ),
    [
        ("2026-01-01 00:00:00+00", "2026-01-01 00:15:00+00", -1, 2, 1, 1.5, 10),
        ("2026-01-01 00:15:00+00", "2026-01-01 00:30:00+00", 2, 1.5, 1, 1.2, 10),
        ("2026-01-01 00:30:00+00", "2026-01-01 00:45:00+00", 2, 3, 1.5, 1.2, 10),
        ("2026-01-01 01:00:00+00", "2026-01-01 00:45:00+00", 2, 3, 1, 2.5, 10),
        ("2026-01-01 01:15:00+00", "2026-01-01 01:30:00+00", 2, 3, 1, 2.5, -1),
    ],
)
def test_database_rejects_invalid_candles(
    test_database_url,
    monkeypatch,
    opened_at,
    closed_at,
    open_price,
    high_price,
    low_price,
    close_price,
    trade_count,
):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO candles "
                "(asset_id, opened_at, closed_at, open_price, high_price, low_price, "
                "close_price, volume, trade_count) "
                "SELECT id, :opened_at, :closed_at, :open_price, :high_price, :low_price, "
                ":close_price, 1, :trade_count FROM assets WHERE symbol = 'BTCBRL'"
            ),
            {
                "opened_at": opened_at,
                "closed_at": closed_at,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "trade_count": trade_count,
            },
        )

    engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO risk_snapshots "
        "(asset_id, calculated_at, last_price, staleness_minutes) "
        "SELECT id, now(), 0, 0 FROM assets WHERE symbol = 'BTCBRL'",
        "INSERT INTO risk_snapshots "
        "(asset_id, calculated_at, last_price, volatility_24h_pct, staleness_minutes) "
        "SELECT id, now(), 1, -1, 0 FROM assets WHERE symbol = 'BTCBRL'",
        "INSERT INTO risk_snapshots "
        "(asset_id, calculated_at, last_price, volume_ratio, staleness_minutes) "
        "SELECT id, now(), 1, -1, 0 FROM assets WHERE symbol = 'BTCBRL'",
        "INSERT INTO risk_snapshots "
        "(asset_id, calculated_at, last_price, staleness_minutes) "
        "SELECT id, now(), 1, -1 FROM assets WHERE symbol = 'BTCBRL'",
        "INSERT INTO ingestion_runs "
        "(status, source, started_at, duration_ms, candles_received, candles_upserted) "
        "VALUES ('success', 'test', now(), -1, 0, 0)",
        "INSERT INTO ingestion_runs "
        "(status, source, started_at, candles_received, candles_upserted) "
        "VALUES ('success', 'test', now(), -1, 0)",
        "INSERT INTO ingestion_runs "
        "(status, source, started_at, candles_received, candles_upserted) "
        "VALUES ('success', 'test', now(), 0, -1)",
    ],
)
def test_database_rejects_invalid_operational_metrics(
    test_database_url,
    monkeypatch,
    statement,
):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text(statement))

    engine.dispose()


def test_runtime_database_roles_enforce_least_privilege(test_database_url, monkeypatch):
    writer_password = "writer-test-password"
    web_password = "web-test-password"
    admin_engine = create_engine(test_database_url)
    with admin_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("DROP ROLE IF EXISTS crypto_writer"))
        connection.execute(text("DROP ROLE IF EXISTS crypto_web"))
        connection.execute(text(f"CREATE ROLE crypto_writer LOGIN PASSWORD '{writer_password}'"))
        connection.execute(text(f"CREATE ROLE crypto_web LOGIN PASSWORD '{web_password}'"))

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    admin_url = make_url(test_database_url)
    writer_engine = create_engine(admin_url.set(username="crypto_writer", password=writer_password))
    web_engine = create_engine(admin_url.set(username="crypto_web", password=web_password))

    try:
        with writer_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ingestion_runs "
                    "(status, source, started_at, candles_received, candles_upserted) "
                    "VALUES ('success', 'permission-test', now(), 0, 0)"
                )
            )
        with pytest.raises(DBAPIError), writer_engine.begin() as connection:
            connection.execute(text("CREATE TABLE writer_must_not_create_tables (id int)"))

        with web_engine.begin() as connection:
            assert connection.scalar(text("SELECT count(*) FROM assets")) == 4
            connection.execute(
                text(
                    "INSERT INTO portfolio_positions (asset_id, quantity) "
                    "SELECT id, 0.01 FROM assets WHERE symbol = 'BTCBRL'"
                )
            )
        with pytest.raises(DBAPIError), web_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candles "
                    "(asset_id, opened_at, closed_at, open_price, high_price, "
                    "low_price, close_price, volume, trade_count) "
                    "SELECT id, now(), now(), 1, 1, 1, 1, 1, 1 "
                    "FROM assets WHERE symbol = 'BTCBRL'"
                )
            )

        command.downgrade(config, "0003_unique_snapshots")
        with admin_engine.begin() as connection:
            connection.execute(text("CREATE TABLE downgrade_privilege_probe (id int)"))
            connection.execute(text("GRANT USAGE ON SCHEMA public TO crypto_writer"))
        with pytest.raises(DBAPIError), writer_engine.begin() as connection:
            connection.execute(text("SELECT * FROM downgrade_privilege_probe"))
    finally:
        writer_engine.dispose()
        web_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text("DROP OWNED BY crypto_writer"))
            connection.execute(text("DROP OWNED BY crypto_web"))
            connection.execute(text("DROP ROLE crypto_writer"))
            connection.execute(text("DROP ROLE crypto_web"))
        admin_engine.dispose()
