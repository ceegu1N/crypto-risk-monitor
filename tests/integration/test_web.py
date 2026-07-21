from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.main import create_app


@pytest.fixture
def web_client(test_database_url, monkeypatch):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    settings = Settings(
        _env_file=None,
        database_url=test_database_url,
        operator_password="test-password",
        session_secret="a-test-secret-that-is-long-enough",
    )
    app = create_app(
        settings=settings,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
    )
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_dashboard_contains_six_operational_views_and_static_assets(web_client):
    response = web_client.get("/")

    assert response.status_code == 200
    assert "Crypto Risk Monitor" in response.text
    for view in ("market", "asset", "portfolio", "alerts", "rules", "system"):
        assert f'data-view="{view}"' in response.text
    assert web_client.get("/static/app.css").status_code == 200
    assert web_client.get("/static/app.js").status_code == 200
