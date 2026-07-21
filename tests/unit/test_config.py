from app.config import Settings


def test_default_symbols(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )

    settings = Settings(_env_file=None)

    assert settings.symbols == ("BTCBRL", "ETHBRL", "SOLBRL", "USDTBRL")


def test_symbols_can_be_configured_from_a_comma_separated_value(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/crypto_risk",
    )
    monkeypatch.setenv("SYMBOLS", "BTCBRL, SOLBRL")

    settings = Settings(_env_file=None)

    assert settings.symbols == ("BTCBRL", "SOLBRL")
