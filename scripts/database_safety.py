from sqlalchemy.engine import make_url


def validate_test_database_url(
    database_url: str,
    *,
    production_url: str | None = None,
) -> str:
    """Reject destructive test execution against an application database."""
    parsed = make_url(database_url)
    database_name = (parsed.database or "").casefold()
    if not parsed.drivername.startswith("postgresql") or "test" not in database_name:
        raise ValueError(
            "TEST_DATABASE_URL must identify a PostgreSQL test database whose name contains 'test'"
        )
    if production_url and parsed == make_url(production_url):
        raise ValueError("TEST_DATABASE_URL must not be equal to DATABASE_URL")
    return database_url
