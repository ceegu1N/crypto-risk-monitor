import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import Settings


def bootstrap_database(settings: Settings | None = None) -> None:
    current_settings = settings or Settings()  # type: ignore[call-arg]
    os.environ["DATABASE_URL"] = current_settings.database_url
    project_root = Path(__file__).parents[1]
    command.upgrade(Config(str(project_root / "alembic.ini")), "head")


if __name__ == "__main__":
    bootstrap_database()
