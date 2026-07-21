"""Grant least-privilege access to the collector and web database roles."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_runtime_permissions"
down_revision: str | None = "0003_unique_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_writer') THEN
                EXECUTE format(
                    'GRANT CONNECT ON DATABASE %I TO crypto_writer',
                    current_database()
                );
                GRANT USAGE ON SCHEMA public TO crypto_writer;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO crypto_writer;
                GRANT USAGE, SELECT
                    ON ALL SEQUENCES IN SCHEMA public TO crypto_writer;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') THEN
                EXECUTE format(
                    'GRANT CONNECT ON DATABASE %I TO crypto_web',
                    current_database()
                );
                GRANT USAGE ON SCHEMA public TO crypto_web;
                GRANT SELECT ON ALL TABLES IN SCHEMA public TO crypto_web;
                GRANT INSERT, UPDATE, DELETE ON portfolio_positions TO crypto_web;
                GRANT UPDATE ON alert_rules, alerts TO crypto_web;
                GRANT INSERT ON alert_events TO crypto_web;
                GRANT USAGE, SELECT
                    ON ALL SEQUENCES IN SCHEMA public TO crypto_web;
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
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM crypto_writer;
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM crypto_writer;
                REVOKE USAGE ON SCHEMA public FROM crypto_writer;
                EXECUTE format(
                    'REVOKE CONNECT ON DATABASE %I FROM crypto_writer',
                    current_database()
                );
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crypto_web') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM crypto_web;
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM crypto_web;
                REVOKE USAGE ON SCHEMA public FROM crypto_web;
                EXECUTE format(
                    'REVOKE CONNECT ON DATABASE %I FROM crypto_web',
                    current_database()
                );
            END IF;
        END
        $$;
        """
    )
