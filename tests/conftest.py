import os

import pytest

from scripts.database_safety import validate_test_database_url


@pytest.fixture
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return validate_test_database_url(
        url,
        production_url=os.getenv("DATABASE_URL"),
    )
