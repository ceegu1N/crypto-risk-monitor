"""Delete anonymous wallets that have not been seen in the last 90 days."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.db import get_session_factory
from app.models import AnonymousPortfolio

RETENTION_DAYS = 90


def main() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    with get_session_factory().begin() as session:
        result = session.execute(
            delete(AnonymousPortfolio).where(AnonymousPortfolio.last_seen_at < cutoff)
        )
    print(f"carteiras removidas: {result.rowcount}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
