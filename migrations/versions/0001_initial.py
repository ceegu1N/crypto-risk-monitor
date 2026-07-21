"""Create the initial market risk schema and seed reference data."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("base_asset", sa.String(20), nullable=False),
        sa.Column("quote_asset", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("symbol", name="uq_assets_symbol"),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile", sa.String(30), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("metric", sa.String(80), nullable=False),
        sa.Column("operator", sa.String(8), nullable=False),
        sa.Column("threshold", sa.Numeric(20, 8), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(12), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("operator IN ('gte', 'lte')", name="ck_alert_rules_valid_operator"),
        sa.CheckConstraint(
            "scope IN ('market', 'portfolio', 'system')", name="ck_alert_rules_valid_scope"
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'high', 'critical')",
            name="ck_alert_rules_valid_severity",
        ),
        sa.UniqueConstraint("profile", "code", name="uq_alert_rules_profile_code"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="binance"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("candles_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candles_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_ingestion_runs_valid_status",
        ),
    )
    op.create_index("ix_ingestion_runs_started", "ingestion_runs", ["started_at"])
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("high_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("low_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("close_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("volume", sa.Numeric(36, 12), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("high_price >= low_price", name="ck_candles_high_not_below_low"),
        sa.CheckConstraint("volume >= 0", name="ck_candles_volume_non_negative"),
        sa.UniqueConstraint("asset_id", "opened_at", name="uq_candles_asset_opened"),
    )
    op.create_index("ix_candles_asset_opened_desc", "candles", ["asset_id", "opened_at"])
    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("return_1h_pct", sa.Numeric(20, 8)),
        sa.Column("return_24h_pct", sa.Numeric(20, 8)),
        sa.Column("volatility_24h_pct", sa.Numeric(20, 8)),
        sa.Column("drawdown_7d_pct", sa.Numeric(20, 8)),
        sa.Column("volume_ratio", sa.Numeric(20, 8)),
        sa.Column("staleness_minutes", sa.Numeric(20, 8), nullable=False),
    )
    op.create_index(
        "ix_risk_snapshots_asset_calculated",
        "risk_snapshots",
        ["asset_id", "calculated_at"],
    )
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(36, 12), nullable=False),
        sa.Column("cost_basis_brl", sa.Numeric(30, 12)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("quantity > 0", name="ck_portfolio_positions_quantity_positive"),
        sa.CheckConstraint(
            "cost_basis_brl IS NULL OR cost_basis_brl > 0",
            name="ck_portfolio_positions_cost_positive",
        ),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="SET NULL")),
        sa.Column("dedupe_key", sa.String(180), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("condition_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("observed_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("threshold", sa.Numeric(20, 8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('new', 'acknowledged', 'resolved', 'dismissed')",
            name="ck_alerts_valid_status",
        ),
    )
    op.create_index("ix_alerts_status_last_triggered", "alerts", ["status", "last_triggered_at"])
    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False, server_default="system"),
        sa.Column("details", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_alert_events_alert_created", "alert_events", ["alert_id", "created_at"])

    assets = sa.table(
        "assets",
        sa.column("symbol", sa.String),
        sa.column("base_asset", sa.String),
        sa.column("quote_asset", sa.String),
        sa.column("display_name", sa.String),
    )
    op.bulk_insert(
        assets,
        [
            {
                "symbol": "BTCBRL",
                "base_asset": "BTC",
                "quote_asset": "BRL",
                "display_name": "Bitcoin",
            },
            {
                "symbol": "ETHBRL",
                "base_asset": "ETH",
                "quote_asset": "BRL",
                "display_name": "Ethereum",
            },
            {
                "symbol": "SOLBRL",
                "base_asset": "SOL",
                "quote_asset": "BRL",
                "display_name": "Solana",
            },
            {
                "symbol": "USDTBRL",
                "base_asset": "USDT",
                "quote_asset": "BRL",
                "display_name": "Tether USD",
            },
        ],
    )
    _seed_moderate_rules()


def _seed_moderate_rules() -> None:
    rules = sa.table(
        "alert_rules",
        sa.column("profile", sa.String),
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("metric", sa.String),
        sa.column("operator", sa.String),
        sa.column("threshold", sa.Numeric),
        sa.column("severity", sa.String),
        sa.column("scope", sa.String),
        sa.column("unit", sa.String),
    )
    op.bulk_insert(
        rules,
        [
            _rule(
                "price_drop_24h",
                "Queda em 24 horas",
                "return_24h_pct",
                "lte",
                -5,
                "high",
                "market",
                "%",
            ),
            _rule(
                "volatility_24h",
                "Volatilidade em 24 horas",
                "volatility_24h_pct",
                "gte",
                4,
                "warning",
                "market",
                "%",
            ),
            _rule(
                "volume_spike",
                "Pico de volume",
                "volume_ratio",
                "gte",
                2.5,
                "warning",
                "market",
                "x",
            ),
            _rule(
                "stale_market_data",
                "Dados de mercado atrasados",
                "staleness_minutes",
                "gte",
                45,
                "critical",
                "market",
                "min",
            ),
            _rule(
                "portfolio_concentration",
                "Concentracao do portfolio",
                "max_position_weight_pct",
                "gte",
                60,
                "high",
                "portfolio",
                "%",
            ),
            _rule(
                "volatile_asset_share",
                "Exposicao a ativos volateis",
                "volatile_asset_share_pct",
                "gte",
                90,
                "warning",
                "portfolio",
                "%",
            ),
        ],
    )


def _rule(
    code: str,
    label: str,
    metric: str,
    operator: str,
    threshold: float,
    severity: str,
    scope: str,
    unit: str,
) -> dict[str, object]:
    return {
        "profile": "moderate",
        "code": code,
        "label": label,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "scope": scope,
        "unit": unit,
    }


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("portfolio_positions")
    op.drop_table("risk_snapshots")
    op.drop_table("candles")
    op.drop_table("ingestion_runs")
    op.drop_table("alert_rules")
    op.drop_table("assets")
