"""Enforce market and ingestion data integrity at the database boundary."""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_data_integrity_constraints"
down_revision: str | None = "0005_persisted_risk_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_candles_prices_positive",
        "candles",
        "open_price > 0 AND high_price > 0 AND low_price > 0 AND close_price > 0",
    )
    op.create_check_constraint(
        "ck_candles_high_contains_open_close",
        "candles",
        "high_price >= open_price AND high_price >= close_price",
    )
    op.create_check_constraint(
        "ck_candles_low_contains_open_close",
        "candles",
        "low_price <= open_price AND low_price <= close_price",
    )
    op.create_check_constraint(
        "ck_candles_valid_time_window",
        "candles",
        "closed_at > opened_at",
    )
    op.create_check_constraint(
        "ck_candles_trade_count_non_negative",
        "candles",
        "trade_count >= 0",
    )

    op.create_check_constraint(
        "ck_risk_snapshots_last_price_positive",
        "risk_snapshots",
        "last_price > 0",
    )
    op.create_check_constraint(
        "ck_risk_snapshots_volatility_non_negative",
        "risk_snapshots",
        "volatility_24h_pct IS NULL OR volatility_24h_pct >= 0",
    )
    op.create_check_constraint(
        "ck_risk_snapshots_volume_ratio_non_negative",
        "risk_snapshots",
        "volume_ratio IS NULL OR volume_ratio >= 0",
    )
    op.create_check_constraint(
        "ck_risk_snapshots_staleness_non_negative",
        "risk_snapshots",
        "staleness_minutes >= 0",
    )

    op.create_check_constraint(
        "ck_ingestion_runs_duration_non_negative",
        "ingestion_runs",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.create_check_constraint(
        "ck_ingestion_runs_received_non_negative",
        "ingestion_runs",
        "candles_received >= 0",
    )
    op.create_check_constraint(
        "ck_ingestion_runs_upserted_non_negative",
        "ingestion_runs",
        "candles_upserted >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ingestion_runs_upserted_non_negative",
        "ingestion_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingestion_runs_received_non_negative",
        "ingestion_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ingestion_runs_duration_non_negative",
        "ingestion_runs",
        type_="check",
    )

    op.drop_constraint(
        "ck_risk_snapshots_staleness_non_negative",
        "risk_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_risk_snapshots_volume_ratio_non_negative",
        "risk_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_risk_snapshots_volatility_non_negative",
        "risk_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_risk_snapshots_last_price_positive",
        "risk_snapshots",
        type_="check",
    )

    op.drop_constraint(
        "ck_candles_trade_count_non_negative",
        "candles",
        type_="check",
    )
    op.drop_constraint("ck_candles_valid_time_window", "candles", type_="check")
    op.drop_constraint(
        "ck_candles_low_contains_open_close",
        "candles",
        type_="check",
    )
    op.drop_constraint(
        "ck_candles_high_contains_open_close",
        "candles",
        type_="check",
    )
    op.drop_constraint("ck_candles_prices_positive", "candles", type_="check")
