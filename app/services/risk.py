from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.metrics import CANDLES_PER_WEEK, calculate_market_metrics
from app.models import Asset, Candle, RiskSnapshot


def create_risk_snapshot(
    session: Session,
    asset: Asset,
    *,
    calculated_at: datetime,
) -> RiskSnapshot | None:
    candles = list(
        session.scalars(
            select(Candle)
            .where(Candle.asset_id == asset.id)
            .order_by(Candle.opened_at.desc())
            .limit(CANDLES_PER_WEEK)
        )
    )
    if not candles:
        return None
    candles.reverse()
    metrics = calculate_market_metrics(
        [candle.close_price for candle in candles],
        [candle.volume for candle in candles],
    )
    staleness = max((calculated_at - candles[-1].closed_at).total_seconds() / 60.0, 0.0)
    values = {
        "asset_id": asset.id,
        "calculated_at": calculated_at,
        "last_price": _decimal(metrics.last_price),
        "return_1h_pct": _optional_decimal(metrics.return_1h_pct),
        "return_24h_pct": _optional_decimal(metrics.return_24h_pct),
        "volatility_24h_pct": _optional_decimal(metrics.volatility_24h_pct),
        "drawdown_7d_pct": _optional_decimal(metrics.drawdown_7d_pct),
        "volume_ratio": _optional_decimal(metrics.volume_ratio),
        "staleness_minutes": _decimal(staleness),
    }
    statement = insert(RiskSnapshot).values(**values)
    snapshot_id = session.scalar(
        statement.on_conflict_do_update(
            index_elements=[RiskSnapshot.asset_id, RiskSnapshot.calculated_at],
            set_={
                key: value
                for key, value in values.items()
                if key not in {"asset_id", "calculated_at"}
            },
        ).returning(RiskSnapshot.id)
    )
    if snapshot_id is None:
        raise RuntimeError("risk snapshot upsert did not return an identifier")
    snapshot = session.get(RiskSnapshot, snapshot_id)
    if snapshot is None:
        raise RuntimeError(f"risk snapshot {snapshot_id} was not persisted")
    return snapshot


def effective_staleness_minutes(
    snapshot: RiskSnapshot,
    *,
    observed_at: datetime | None = None,
) -> float:
    """Age a persisted staleness value as wall-clock time advances."""
    current = observed_at or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    elapsed = max((current - snapshot.calculated_at).total_seconds() / 60.0, 0.0)
    return float(snapshot.staleness_minutes) + elapsed


def _optional_decimal(value: float | None) -> Decimal | None:
    return _decimal(value) if value is not None else None


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
