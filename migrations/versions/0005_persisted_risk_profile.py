"""Persist the active risk profile and add a customizable profile."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_persisted_risk_profile"
down_revision: str | None = "0004_runtime_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.String(160), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        """
        INSERT INTO alert_rules
            (profile, code, label, metric, operator, threshold, severity, scope, unit, enabled)
        SELECT
            'custom', code, label, metric, operator, threshold, severity, scope, unit, enabled
        FROM alert_rules
        WHERE profile = 'moderate'
        ORDER BY id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_writer') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON app_settings TO crypto_writer;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') THEN
                GRANT SELECT, INSERT, UPDATE ON app_settings TO crypto_web;
            END IF;
        END
        $$;
        """
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
    custom_rule_ids = sa.select(alert_rules.c.id).where(alert_rules.c.profile == "custom")
    custom_alert_ids = sa.select(alerts.c.id).where(alerts.c.rule_id.in_(custom_rule_ids))
    connection = op.get_bind()
    connection.execute(sa.delete(alert_events).where(alert_events.c.alert_id.in_(custom_alert_ids)))
    connection.execute(sa.delete(alerts).where(alerts.c.rule_id.in_(custom_rule_ids)))
    connection.execute(sa.delete(alert_rules).where(alert_rules.c.profile == "custom"))
    op.drop_table("app_settings")
