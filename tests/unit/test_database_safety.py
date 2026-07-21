from importlib import import_module

import pytest


def _validate(url: str, production_url: str | None = None) -> str:
    module = import_module("scripts.database_safety")
    return module.validate_test_database_url(url, production_url=production_url)


def test_test_database_guard_rejects_a_database_without_test_marker():
    with pytest.raises(ValueError, match="test database"):
        _validate("postgresql+psycopg://postgres:postgres@localhost/crypto_risk")


def test_test_database_guard_rejects_the_application_database():
    url = "postgresql+psycopg://postgres:postgres@localhost/crypto_risk_test"

    with pytest.raises(ValueError, match="DATABASE_URL"):
        _validate(url, production_url=url)


def test_test_database_guard_accepts_an_explicit_test_database():
    url = "postgresql+psycopg://postgres:postgres@localhost/crypto_risk_test"

    assert _validate(url) == url
