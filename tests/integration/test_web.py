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
    assert 'src="/static/vendor/chart.umd.min.js"' in response.text
    assert 'src="/static/vendor/lucide.min.js"' in response.text
    assert 'id="risk-profile-select"' in response.text
    assert 'id="reset-risk-profile"' in response.text
    assert 'id="system-runs-table"' in response.text
    assert 'id="alert-events-dialog"' in response.text
    assert "https://cdn.jsdelivr.net" not in response.text
    assert "https://unpkg.com" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "script-src 'self';" in response.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in response.headers["content-security-policy"]
    assert "unpkg.com" not in response.headers["content-security-policy"]
    assert web_client.get("/static/app.css").status_code == 200
    assert web_client.get("/static/app.js").status_code == 200
    assert web_client.get("/static/favicon.svg").status_code == 200
    assert web_client.get("/static/vendor/chart.umd.min.js").status_code == 200
    assert web_client.get("/static/vendor/lucide.min.js").status_code == 200
    javascript = web_client.get("/static/app.js").text
    assert "Promise.allSettled" in javascript
    assert "Atualização parcial" in javascript
    assert "const REFRESH_INTERVAL_MS = 60_000" in javascript
    assert "if (state.refreshing) return" in javascript
    assert "document.hidden" in javascript
    assert "function recoverOperatorSession(error)" in javascript
    assert "Sua sessão expirou. Entre novamente." in javascript
    assert "alertas serão reavaliados na próxima coleta" in javascript
    assert "será aplicada na próxima coleta" in javascript


def test_https_session_cookie_has_strict_browser_protections(web_client, test_database_url):
    settings = Settings(
        _env_file=None,
        database_url=test_database_url,
        operator_password="a-secure-operator-password",
        session_secret="a-production-session-secret-longer-than-thirty-two-characters",
        session_cookie_secure=True,
    )
    app = create_app(
        settings=settings,
        session_factory=web_client.app.state.session_factory,
    )

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/auth/login",
            json={"password": "a-secure-operator-password"},
        )

    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert cookie.startswith("__host-crypto_risk_session=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" in cookie
