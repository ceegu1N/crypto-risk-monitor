"""Make risk snapshots idempotent by asset and calculation time."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_unique_snapshots"
down_revision: str | None = "0002_risk_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM risk_snapshots AS older "
            "USING risk_snapshots AS newer "
            "WHERE older.asset_id = newer.asset_id "
            "AND older.calculated_at = newer.calculated_at "
            "AND older.id < newer.id"
        )
    )
    op.create_unique_constraint(
        "uq_risk_snapshots_asset_calculated",
        "risk_snapshots",
        ["asset_id", "calculated_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_risk_snapshots_asset_calculated",
        "risk_snapshots",
        type_="unique",
    )
