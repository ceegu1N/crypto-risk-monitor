from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite, log, sqrt
from statistics import fmean, pstdev

CANDLES_PER_HOUR = 4
CANDLES_PER_DAY = 96
CANDLES_PER_WEEK = 672


@dataclass(frozen=True, slots=True)
class MarketMetrics:
    last_price: float
    return_1h_pct: float | None
    return_24h_pct: float | None
    volatility_24h_pct: float | None
    drawdown_7d_pct: float | None
    volume_ratio: float | None


def calculate_market_metrics(
    closes: Sequence[float | Decimal],
    volumes: Sequence[float | Decimal],
) -> MarketMetrics:
    """Calculate explainable metrics from chronological 15-minute candles."""
    close_values = _validated_values(closes, name="closes", strictly_positive=True)
    volume_values = _validated_values(volumes, name="volumes", strictly_positive=False)
    if len(close_values) != len(volume_values):
        raise ValueError("closes and volumes must have the same length")

    return MarketMetrics(
        last_price=close_values[-1],
        return_1h_pct=_period_return(close_values, CANDLES_PER_HOUR),
        return_24h_pct=_period_return(close_values, CANDLES_PER_DAY),
        volatility_24h_pct=_daily_volatility(close_values),
        drawdown_7d_pct=_weekly_drawdown(close_values),
        volume_ratio=_daily_volume_ratio(volume_values),
    )


def _validated_values(
    values: Sequence[float | Decimal],
    *,
    name: str,
    strictly_positive: bool,
) -> list[float]:
    if not values:
        raise ValueError(f"{name} cannot be empty")
    converted = [float(value) for value in values]
    if any(not isfinite(value) for value in converted):
        raise ValueError(f"{name} must contain finite values")
    if strictly_positive and any(value <= 0 for value in converted):
        raise ValueError(f"{name} must contain positive values")
    if not strictly_positive and any(value < 0 for value in converted):
        raise ValueError(f"{name} cannot contain negative values")
    return converted


def _period_return(values: Sequence[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return (values[-1] / values[-periods - 1] - 1.0) * 100.0


def _daily_volatility(values: Sequence[float]) -> float | None:
    if len(values) <= CANDLES_PER_DAY:
        return None
    window = values[-(CANDLES_PER_DAY + 1) :]
    log_returns = [
        log(current / previous) for previous, current in zip(window, window[1:], strict=False)
    ]
    return pstdev(log_returns) * sqrt(CANDLES_PER_DAY) * 100.0


def _weekly_drawdown(values: Sequence[float]) -> float | None:
    if len(values) < CANDLES_PER_WEEK:
        return None
    window = values[-CANDLES_PER_WEEK:]
    return (window[-1] / max(window) - 1.0) * 100.0


def _daily_volume_ratio(values: Sequence[float]) -> float | None:
    if len(values) <= CANDLES_PER_DAY:
        return None
    previous_average = fmean(values[-(CANDLES_PER_DAY + 1) : -1])
    if previous_average == 0:
        return None
    return values[-1] / previous_average
