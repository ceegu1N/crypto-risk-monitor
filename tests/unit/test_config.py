import pytest

from app.config import Settings


def test_default_symbols(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )

    settings = Settings(_env_file=None)

    assert settings.symbols == (
        "BTCBRL",
        "ETHBRL",
        "SOLBRL",
        "USDTBRL",
        "ADABRL",
        "PEPEBRL",
        "NEARBRL",
    )


def test_symbols_can_be_configured_from_a_comma_separated_value(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )
    monkeypatch.setenv("SYMBOLS", "BTCBRL, SOLBRL")

    settings = Settings(_env_file=None)

    assert settings.symbols == ("BTCBRL", "SOLBRL")


def test_empty_optional_values_in_env_file_are_ignored(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://user:password@localhost/crypto_risk\n"
        "DISCORD_WEBHOOK_URL=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.discord_webhook_url is None


def test_secure_web_mode_rejects_placeholder_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )

    settings = Settings(_env_file=None, session_cookie_secure=True)

    with pytest.raises(ValueError, match="OPERATOR_PASSWORD"):
        settings.validate_web_security()


def test_secure_web_mode_accepts_explicit_strong_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )
    settings = Settings(
        _env_file=None,
        session_cookie_secure=True,
        operator_password="a-long-operator-password",
        session_secret="a-session-secret-with-more-than-thirty-two-characters",
    )

    settings.validate_web_security()
