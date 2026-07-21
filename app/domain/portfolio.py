from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: float
    cost_basis_brl: float | None = None


@dataclass(frozen=True, slots=True)
class PositionMetrics:
    symbol: str
    quantity: float
    price_brl: float
    current_value_brl: float
    weight_pct: float
    cost_basis_brl: float | None
    pnl_brl: float | None
    pnl_pct: float | None
    volatility_24h_pct: float | None
    risk_contribution: float | None


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    total_value_brl: float
    cost_basis_value_brl: float | None
    pnl_brl: float | None
    pnl_pct: float | None
    max_weight_pct: float
    volatile_asset_share_pct: float
    positions: tuple[PositionMetrics, ...]
    risk_contribution_note: str = (
        "Indicador aproximado calculado como peso vezes volatilidade; nao representa VaR "
        "nem previsao de perda."
    )


def calculate_portfolio(
    positions: Sequence[Position],
    prices: Mapping[str, float],
    volatilities: Mapping[str, float | None],
    *,
    stable_symbols: frozenset[str] = frozenset({"USDTBRL"}),
) -> PortfolioMetrics:
    """Value a simulated portfolio using current market prices."""
    if not positions:
        return PortfolioMetrics(0.0, None, None, None, 0.0, 0.0, ())

    normalized: list[tuple[Position, str, float, float]] = []
    seen: set[str] = set()
    for position in positions:
        symbol = position.symbol.strip().upper()
        if symbol in seen:
            raise ValueError(f"duplicate position for {symbol}")
        seen.add(symbol)
        quantity = _positive_number(position.quantity, f"quantity for {symbol}")
        if position.cost_basis_brl is not None:
            _positive_number(position.cost_basis_brl, f"cost basis for {symbol}")
        if symbol not in prices:
            raise ValueError(f"missing price for {symbol}")
        price = _positive_number(prices[symbol], f"price for {symbol}")
        normalized.append((position, symbol, quantity, price))

    total_value = sum(quantity * price for _, _, quantity, price in normalized)
    metrics: list[PositionMetrics] = []
    volatile_value = 0.0
    for position, symbol, quantity, price in normalized:
        current_value = quantity * price
        weight_pct = current_value / total_value * 100.0
        if symbol not in stable_symbols:
            volatile_value += current_value

        cost_basis = (
            float(position.cost_basis_brl) if position.cost_basis_brl is not None else None
        )
        pnl_brl = quantity * (price - cost_basis) if cost_basis is not None else None
        pnl_pct = (price / cost_basis - 1.0) * 100.0 if cost_basis is not None else None

        volatility = _optional_non_negative(volatilities.get(symbol), f"volatility for {symbol}")
        contribution = weight_pct / 100.0 * volatility if volatility is not None else None
        metrics.append(
            PositionMetrics(
                symbol=symbol,
                quantity=quantity,
                price_brl=price,
                current_value_brl=current_value,
                weight_pct=weight_pct,
                cost_basis_brl=cost_basis,
                pnl_brl=pnl_brl,
                pnl_pct=pnl_pct,
                volatility_24h_pct=volatility,
                risk_contribution=contribution,
            )
        )

    has_complete_cost_basis = all(item.cost_basis_brl is not None for item in metrics)
    cost_value = (
        sum(
            item.quantity * item.cost_basis_brl
            for item in metrics
            if item.cost_basis_brl is not None
        )
        if has_complete_cost_basis
        else None
    )
    pnl_brl = total_value - cost_value if cost_value is not None else None
    pnl_pct = (total_value / cost_value - 1.0) * 100.0 if cost_value is not None else None

    return PortfolioMetrics(
        total_value_brl=total_value,
        cost_basis_value_brl=cost_value,
        pnl_brl=pnl_brl,
        pnl_pct=pnl_pct,
        max_weight_pct=max(item.weight_pct for item in metrics),
        volatile_asset_share_pct=volatile_value / total_value * 100.0,
        positions=tuple(metrics),
    )


def _positive_number(value: float, label: str) -> float:
    converted = float(value)
    if not isfinite(converted) or converted <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return converted


def _optional_non_negative(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    converted = float(value)
    if not isfinite(converted) or converted < 0:
        raise ValueError(f"{label} must be a non-negative finite number")
    return converted
