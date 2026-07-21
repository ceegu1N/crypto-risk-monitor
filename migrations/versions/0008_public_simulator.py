"""Add anonymous paper-trading wallets and immutable simulated trades."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_public_simulator"
down_revision: str | None = "0007_polish_portuguese_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anonymous_portfolios",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column(
            "cash_brl",
            sa.Numeric(36, 12),
            nullable=False,
            server_default=sa.text("10000"),
        ),
        sa.Column(
            "realized_pnl_brl",
            sa.Numeric(36, 12),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_anonymous_portfolios"),
        sa.UniqueConstraint("identity_hash", name="uq_anonymous_portfolios_identity_hash"),
        sa.CheckConstraint("cash_brl >= 0", name="ck_anonymous_portfolios_cash_non_negative"),
    )
    op.create_index(
        "ix_anonymous_portfolios_last_seen",
        "anonymous_portfolios",
        ["last_seen_at"],
    )

    op.create_table(
        "simulated_positions",
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 12), nullable=False),
        sa.Column("average_price_brl", sa.Numeric(30, 12), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_simulated_positions_asset_id_assets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["anonymous_portfolios.id"],
            name="fk_simulated_positions_portfolio_id_anonymous_portfolios",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "portfolio_id",
            "asset_id",
            name="pk_simulated_positions",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_simulated_positions_quantity_positive"),
        sa.CheckConstraint(
            "average_price_brl > 0",
            name="ck_simulated_positions_average_price_positive",
        ),
    )

    op.create_table(
        "simulated_trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 12), nullable=False),
        sa.Column("price_brl", sa.Numeric(30, 12), nullable=False),
        sa.Column("notional_brl", sa.Numeric(36, 12), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.String(24), nullable=False, server_default="web"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_simulated_trades_asset_id_assets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["anonymous_portfolios.id"],
            name="fk_simulated_trades_portfolio_id_anonymous_portfolios",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulated_trades"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_simulated_trades_valid_side"),
        sa.CheckConstraint("quantity > 0", name="ck_simulated_trades_quantity_positive"),
        sa.CheckConstraint("price_brl > 0", name="ck_simulated_trades_price_positive"),
        sa.CheckConstraint("notional_brl > 0", name="ck_simulated_trades_notional_positive"),
    )
    op.create_index(
        "ix_simulated_trades_portfolio_executed",
        "simulated_trades",
        ["portfolio_id", "executed_at"],
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_writer') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON anonymous_portfolios, simulated_positions, simulated_trades
                    TO crypto_writer;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO crypto_writer;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON anonymous_portfolios, simulated_positions, simulated_trades
                    TO crypto_web;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO crypto_web;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_writer') THEN
                REVOKE ALL PRIVILEGES ON anonymous_portfolios, simulated_positions,
                    simulated_trades FROM crypto_writer;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') THEN
                REVOKE ALL PRIVILEGES ON anonymous_portfolios, simulated_positions,
                    simulated_trades FROM crypto_web;
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_simulated_trades_portfolio_executed", table_name="simulated_trades")
    op.drop_table("simulated_trades")
    op.drop_table("simulated_positions")
    op.drop_index("ix_anonymous_portfolios_last_seen", table_name="anonymous_portfolios")
    op.drop_table("anonymous_portfolios")
