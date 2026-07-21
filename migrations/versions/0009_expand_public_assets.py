"""Add the volatile BRL pairs used by the public simulator."""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_expand_public_assets"
down_revision: str | None = "0008_public_simulator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO assets (symbol, base_asset, quote_asset, display_name)
        VALUES
            ('ADABRL', 'ADA', 'BRL', 'Cardano'),
            ('PEPEBRL', 'PEPE', 'BRL', 'Pepe'),
            ('NEARBRL', 'NEAR', 'BRL', 'NEAR Protocol')
        ON CONFLICT (symbol) DO UPDATE
            SET base_asset = EXCLUDED.base_asset,
                quote_asset = EXCLUDED.quote_asset,
                display_name = EXCLUDED.display_name,
                active = TRUE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM assets
        WHERE symbol IN ('ADABRL', 'PEPEBRL', 'NEARBRL')
        """
    )
