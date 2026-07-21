"""Seed conservative and aggressive risk profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_risk_profiles"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        _profile_rules(
            "conservative",
            price_drop=-3,
            volatility=3,
            volume_ratio=2,
            stale_minutes=30,
            max_position=50,
            volatile_share=80,
        )
        + _profile_rules(
            "aggressive",
            price_drop=-8,
            volatility=6,
            volume_ratio=4,
            stale_minutes=90,
            max_position=75,
            volatile_share=95,
        ),
    )


def downgrade() -> None:
    alert_rules = sa.table(
        "alert_rules",
        sa.column("id", sa.Integer),
        sa.column("profile", sa.String),
    )
    alerts = sa.table(
        "alerts",
        sa.column("id", sa.BigInteger),
        sa.column("rule_id", sa.Integer),
    )
    alert_events = sa.table(
        "alert_events",
        sa.column("alert_id", sa.BigInteger),
    )
    profiles = ("conservative", "aggressive")
    rule_ids = sa.select(alert_rules.c.id).where(alert_rules.c.profile.in_(profiles))
    alert_ids = sa.select(alerts.c.id).where(alerts.c.rule_id.in_(rule_ids))
    connection = op.get_bind()
    connection.execute(sa.delete(alert_events).where(alert_events.c.alert_id.in_(alert_ids)))
    connection.execute(sa.delete(alerts).where(alerts.c.rule_id.in_(rule_ids)))
    connection.execute(sa.delete(alert_rules).where(alert_rules.c.profile.in_(profiles)))


def _profile_rules(
    profile: str,
    *,
    price_drop: float,
    volatility: float,
    volume_ratio: float,
    stale_minutes: float,
    max_position: float,
    volatile_share: float,
) -> list[dict[str, object]]:
    return [
        _rule(
            profile,
            "price_drop_24h",
            "Queda em 24 horas",
            "return_24h_pct",
            "lte",
            price_drop,
            "high",
            "market",
            "%",
        ),
        _rule(
            profile,
            "volatility_24h",
            "Volatilidade em 24 horas",
            "volatility_24h_pct",
            "gte",
            volatility,
            "warning",
            "market",
            "%",
        ),
        _rule(
            profile,
            "volume_spike",
            "Pico de volume",
            "volume_ratio",
            "gte",
            volume_ratio,
            "warning",
            "market",
            "x",
        ),
        _rule(
            profile,
            "stale_market_data",
            "Dados de mercado atrasados",
            "staleness_minutes",
            "gte",
            stale_minutes,
            "critical",
            "market",
            "min",
        ),
        _rule(
            profile,
            "portfolio_concentration",
            "Concentracao do portfolio",
            "max_position_weight_pct",
            "gte",
            max_position,
            "high",
            "portfolio",
            "%",
        ),
        _rule(
            profile,
            "volatile_asset_share",
            "Exposicao a ativos volateis",
            "volatile_asset_share_pct",
            "gte",
            volatile_share,
            "warning",
            "portfolio",
            "%",
        ),
    ]


def _rule(
    profile: str,
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
        "profile": profile,
        "code": code,
        "label": label,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "scope": scope,
        "unit": unit,
    }
