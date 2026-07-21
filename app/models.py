from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PRICE_TYPE = Numeric(30, 12)
VALUE_TYPE = Numeric(36, 12)
METRIC_TYPE = Numeric(20, 8)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    base_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(20), nullable=False, default="BRL")
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    candles: Mapped[list["Candle"]] = relationship(back_populates="asset")
    risk_snapshots: Mapped[list["RiskSnapshot"]] = relationship(back_populates="asset")


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("asset_id", "opened_at", name="uq_candles_asset_opened"),
        CheckConstraint(
            "open_price > 0 AND high_price > 0 AND low_price > 0 AND close_price > 0",
            name="prices_positive",
        ),
        CheckConstraint("high_price >= low_price", name="high_not_below_low"),
        CheckConstraint(
            "high_price >= open_price AND high_price >= close_price",
            name="high_contains_open_close",
        ),
        CheckConstraint(
            "low_price <= open_price AND low_price <= close_price",
            name="low_contains_open_close",
        ),
        CheckConstraint("closed_at > opened_at", name="valid_time_window"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        CheckConstraint("trade_count >= 0", name="trade_count_non_negative"),
        Index("ix_candles_asset_opened_desc", "asset_id", "opened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    high_price: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    low_price: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    close_price: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    asset: Mapped[Asset] = relationship(back_populates="candles")


class RiskSnapshot(Base):
    __tablename__ = "risk_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "calculated_at",
            name="uq_risk_snapshots_asset_calculated",
        ),
        CheckConstraint("last_price > 0", name="last_price_positive"),
        CheckConstraint(
            "volatility_24h_pct IS NULL OR volatility_24h_pct >= 0",
            name="volatility_non_negative",
        ),
        CheckConstraint(
            "volume_ratio IS NULL OR volume_ratio >= 0",
            name="volume_ratio_non_negative",
        ),
        CheckConstraint("staleness_minutes >= 0", name="staleness_non_negative"),
        Index("ix_risk_snapshots_asset_calculated", "asset_id", "calculated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_price: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    return_1h_pct: Mapped[Decimal | None] = mapped_column(METRIC_TYPE)
    return_24h_pct: Mapped[Decimal | None] = mapped_column(METRIC_TYPE)
    volatility_24h_pct: Mapped[Decimal | None] = mapped_column(METRIC_TYPE)
    drawdown_7d_pct: Mapped[Decimal | None] = mapped_column(METRIC_TYPE)
    volume_ratio: Mapped[Decimal | None] = mapped_column(METRIC_TYPE)
    staleness_minutes: Mapped[Decimal] = mapped_column(METRIC_TYPE, nullable=False)

    asset: Mapped[Asset] = relationship(back_populates="risk_snapshots")


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("profile", "code", name="uq_alert_rules_profile_code"),
        CheckConstraint("operator IN ('gte', 'lte')", name="valid_operator"),
        CheckConstraint("scope IN ('market', 'portfolio', 'system')", name="valid_scope"),
        CheckConstraint("severity IN ('warning', 'high', 'critical')", name="valid_severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    operator: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(METRIC_TYPE, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'acknowledged', 'resolved', 'dismissed')",
            name="valid_status",
        ),
        Index("ix_alerts_status_last_triggered", "status", "last_triggered_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    condition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_value: Mapped[Decimal] = mapped_column(METRIC_TYPE, nullable=False)
    threshold: Mapped[Decimal] = mapped_column(METRIC_TYPE, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_created", "alert_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    alert: Mapped[Alert] = relationship(back_populates="events")


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("cost_basis_brl IS NULL OR cost_basis_brl > 0", name="cost_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False)
    cost_basis_brl: Mapped[Decimal | None] = mapped_column(PRICE_TYPE)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AnonymousPortfolio(Base):
    """One persisted paper-trading wallet identified by a hashed browser cookie."""

    __tablename__ = "anonymous_portfolios"
    __table_args__ = (
        CheckConstraint("cash_brl >= 0", name="cash_non_negative"),
        CheckConstraint("realized_pnl_brl IS NOT NULL", name="realized_pnl_present"),
        Index("ix_anonymous_portfolios_last_seen", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    cash_brl: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False, default=Decimal("10000"))
    realized_pnl_brl: Mapped[Decimal] = mapped_column(
        VALUE_TYPE, nullable=False, default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    positions: Mapped[list["SimulatedPosition"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    trades: Mapped[list["SimulatedTrade"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class SimulatedPosition(Base):
    """Current spot position for one anonymous paper-trading wallet."""

    __tablename__ = "simulated_positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("average_price_brl > 0", name="average_price_positive"),
    )

    portfolio_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("anonymous_portfolios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False)
    average_price_brl: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    portfolio: Mapped[AnonymousPortfolio] = relationship(back_populates="positions")
    asset: Mapped[Asset] = relationship()


class SimulatedTrade(Base):
    """Immutable audit record for a simulated spot trade."""

    __tablename__ = "simulated_trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="valid_side"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price_brl > 0", name="price_positive"),
        CheckConstraint("notional_brl > 0", name="notional_positive"),
        Index("ix_simulated_trades_portfolio_executed", "portfolio_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("anonymous_portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False)
    price_brl: Mapped[Decimal] = mapped_column(PRICE_TYPE, nullable=False)
    notional_brl: Mapped[Decimal] = mapped_column(VALUE_TYPE, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="web")

    portfolio: Mapped[AnonymousPortfolio] = relationship(back_populates="trades")
    asset: Mapped[Asset] = relationship()


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'success', 'failed')", name="valid_status"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        CheckConstraint("candles_received >= 0", name="received_non_negative"),
        CheckConstraint("candles_upserted >= 0", name="upserted_non_negative"),
        Index("ix_ingestion_runs_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="binance")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    candles_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candles_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
