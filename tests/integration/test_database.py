from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    }
    assert expected_tables <= set(inspect(engine).get_table_names())

    with engine.connect() as connection:
        asset_count = connection.scalar(text(f"SELECT count(*) FROM {Asset.__tablename__}"))
        rule_count = connection.scalar(text(f"SELECT count(*) FROM {AlertRule.__tablename__}"))
    assert asset_count == 4
    assert rule_count == 6

    engine.dispose()
