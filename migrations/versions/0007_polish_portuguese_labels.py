"""Correct Portuguese labels shown in the risk rules dashboard."""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_polish_portuguese_labels"
down_revision: str | None = "0006_data_integrity_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE alert_rules
        SET label = CASE code
            WHEN 'portfolio_concentration' THEN 'Concentração do portfólio'
            WHEN 'volatile_asset_share' THEN 'Exposição a ativos voláteis'
            ELSE label
        END
        WHERE code IN ('portfolio_concentration', 'volatile_asset_share')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE alert_rules
        SET label = CASE code
            WHEN 'portfolio_concentration' THEN 'Concentracao do portfolio'
            WHEN 'volatile_asset_share' THEN 'Exposicao a ativos volateis'
            ELSE label
        END
        WHERE code IN ('portfolio_concentration', 'volatile_asset_share')
        """
    )
