"""Anonymous paper-trading identity, execution and portfolio summaries."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas import TradeRequest, TradeSide
from app.models import (
    AnonymousPortfolio,
    Asset,
    RiskSnapshot,
    SimulatedPosition,
    SimulatedTrade,
)

INITIAL_CASH_BRL = Decimal("10000")
GUEST_COOKIE_TTL_SECONDS = 90 * 24 * 60 * 60
GUEST_COOKIE_BASE_NAME = "crypto_guest"
QUANTITY_STEP = Decimal("0.000000000001")
STABLE_SYMBOLS = frozenset({"USDTBRL"})


class SimulatorError(ValueError):
    """Expected user-facing error in the paper-trading flow."""


class InsufficientCash(SimulatorError):
    """The wallet does not have enough virtual BRL for the requested buy."""


class InsufficientPosition(SimulatorError):
    """The wallet does not own enough of the selected asset to sell."""


class MarketPriceUnavailable(SimulatorError):
    """A fresh price could not be obtained for a trade."""


def guest_cookie_name(*, secure: bool) -> str:
    return f"__Host-{GUEST_COOKIE_BASE_NAME}" if secure else GUEST_COOKIE_BASE_NAME


def get_or_create_guest_portfolio(
    session: Session,
    request: Request,
    response: Response,
    *,
    secure_cookie: bool,
) -> AnonymousPortfolio:
    """Load a wallet from a hashed cookie and refresh its sliding retention window."""
    cookie_name = guest_cookie_name(secure=secure_cookie)
    raw_token = request.cookies.get(cookie_name)
    token = raw_token if raw_token and 32 <= len(raw_token) <= 256 else secrets.token_urlsafe(32)
    identity_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    portfolio = session.scalar(
        select(AnonymousPortfolio).where(AnonymousPortfolio.identity_hash == identity_hash)
    )
    if portfolio is None:
        portfolio = AnonymousPortfolio(
            identity_hash=identity_hash,
            cash_brl=INITIAL_CASH_BRL,
            realized_pnl_brl=Decimal("0"),
        )
        session.add(portfolio)
        session.flush()

    portfolio.last_seen_at = datetime.now(UTC)
    response.set_cookie(
        cookie_name,
        token,
        max_age=GUEST_COOKIE_TTL_SECONDS,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        path="/",
    )
    return portfolio


def execute_trade(
    session: Session,
    portfolio_id: UUID,
    symbol: str,
    request: TradeRequest,
    *,
    price_brl: Decimal,
    executed_at: datetime | None = None,
) -> SimulatedTrade:
    """Execute one fee-free spot trade atomically against a locked wallet."""
    price = _positive_decimal(price_brl, "price_brl")
    asset = session.scalar(
        select(Asset).where(Asset.symbol == symbol.strip().upper(), Asset.active.is_(True))
    )
    if asset is None:
        raise SimulatorError(f"unknown asset: {symbol}")

    portfolio = session.scalar(
        select(AnonymousPortfolio).where(AnonymousPortfolio.id == portfolio_id).with_for_update()
    )
    if portfolio is None:
        raise SimulatorError("portfolio not found")

    position = session.scalar(
        select(SimulatedPosition)
        .where(
            SimulatedPosition.portfolio_id == portfolio.id,
            SimulatedPosition.asset_id == asset.id,
        )
        .with_for_update()
    )
    quantity = _order_quantity(request, price)
    notional = quantity * price

    if request.side is TradeSide.BUY:
        if notional > portfolio.cash_brl:
            raise InsufficientCash("saldo virtual insuficiente")
        if position is None:
            position = SimulatedPosition(
                portfolio_id=portfolio.id,
                asset_id=asset.id,
                quantity=quantity,
                average_price_brl=price,
            )
            session.add(position)
        else:
            old_value = position.quantity * position.average_price_brl
            position.quantity += quantity
            position.average_price_brl = (old_value + notional) / position.quantity
        portfolio.cash_brl -= notional
    else:
        if position is None or quantity > position.quantity:
            raise InsufficientPosition("quantidade virtual insuficiente")
        portfolio.cash_brl += notional
        portfolio.realized_pnl_brl += quantity * (price - position.average_price_brl)
        remaining = position.quantity - quantity
        if remaining <= 0:
            session.delete(position)
        else:
            position.quantity = remaining

    portfolio.last_seen_at = executed_at or datetime.now(UTC)
    trade = SimulatedTrade(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        side=request.side.value,
        quantity=quantity,
        price_brl=price,
        notional_brl=notional,
        executed_at=executed_at or datetime.now(UTC),
        source="web",
    )
    session.add(trade)
    session.flush()
    return trade


def reset_guest_portfolio(session: Session, portfolio_id: UUID) -> None:
    portfolio = session.scalar(
        select(AnonymousPortfolio).where(AnonymousPortfolio.id == portfolio_id).with_for_update()
    )
    if portfolio is None:
        raise SimulatorError("portfolio not found")
    session.execute(delete(SimulatedPosition).where(SimulatedPosition.portfolio_id == portfolio.id))
    session.execute(delete(SimulatedTrade).where(SimulatedTrade.portfolio_id == portfolio.id))
    portfolio.cash_brl = INITIAL_CASH_BRL
    portfolio.realized_pnl_brl = Decimal("0")
    portfolio.last_seen_at = datetime.now(UTC)


def build_portfolio_summary(session: Session, portfolio: AnonymousPortfolio) -> dict[str, object]:
    """Build a user-facing summary from persisted positions and latest snapshots."""
    rows = session.execute(
        select(SimulatedPosition, Asset)
        .join(Asset, Asset.id == SimulatedPosition.asset_id)
        .where(SimulatedPosition.portfolio_id == portfolio.id)
        .order_by(Asset.symbol)
    ).all()
    prices = _latest_prices(session, [asset.id for _, asset in rows])
    positions: list[dict[str, object]] = []
    invested_value = Decimal("0")
    current_assets_value = Decimal("0")
    for position, asset in rows:
        price = prices.get(asset.id)
        current_value = position.quantity * price if price is not None else None
        cost_basis = position.quantity * position.average_price_brl
        invested_value += cost_basis
        if current_value is not None:
            current_assets_value += current_value
        positions.append(
            {
                "symbol": asset.symbol,
                "display_name": asset.display_name,
                "quantity": float(position.quantity),
                "average_price_brl": float(position.average_price_brl),
                "price_brl": float(price) if price is not None else None,
                "current_value_brl": float(current_value) if current_value is not None else None,
                "pnl_brl": float(current_value - cost_basis) if current_value is not None else None,
            }
        )
    total_value = portfolio.cash_brl + current_assets_value
    pnl = total_value - INITIAL_CASH_BRL
    for item in positions:
        current_value = item["current_value_brl"]
        item["weight_pct"] = (
            float(Decimal(str(current_value)) / total_value * 100)
            if current_value is not None and total_value > 0
            else None
        )
    return {
        "portfolio_id": str(portfolio.id),
        "cash_brl": float(portfolio.cash_brl),
        "invested_value_brl": float(invested_value),
        "total_value_brl": float(total_value),
        "pnl_brl": float(pnl),
        "pnl_pct": float(pnl / INITIAL_CASH_BRL * 100),
        "realized_pnl_brl": float(portfolio.realized_pnl_brl),
        "market_data_ready": all(item["price_brl"] is not None for item in positions),
        "positions": positions,
        "recent_trades": _recent_trades(session, portfolio.id),
        "starting_cash_brl": float(INITIAL_CASH_BRL),
        "disclaimer": "Simulação educativa sem taxas, spread, slippage ou execução real.",
    }


def _order_quantity(request: TradeRequest, price: Decimal) -> Decimal:
    if request.quantity is not None:
        return _positive_quantity(request.quantity)
    if request.notional_brl is None:
        raise SimulatorError("ordem sem quantidade ou valor")
    quantity = (request.notional_brl / price).quantize(QUANTITY_STEP, rounding=ROUND_DOWN)
    return _positive_quantity(quantity)


def _positive_quantity(value: Decimal) -> Decimal:
    normalized = value.quantize(QUANTITY_STEP, rounding=ROUND_DOWN)
    if normalized <= 0:
        raise SimulatorError("quantidade muito pequena")
    return normalized


def _positive_decimal(value: Decimal, label: str) -> Decimal:
    if value <= 0:
        raise SimulatorError(f"{label} must be positive")
    return value


def _latest_prices(session: Session, asset_ids: list[int]) -> dict[int, Decimal]:
    prices: dict[int, Decimal] = {}
    for asset_id in asset_ids:
        snapshot = session.scalar(
            select(RiskSnapshot)
            .where(RiskSnapshot.asset_id == asset_id)
            .order_by(RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc())
            .limit(1)
        )
        if snapshot is not None:
            prices[asset_id] = snapshot.last_price
    return prices


def _recent_trades(session: Session, portfolio_id: UUID) -> list[dict[str, object]]:
    rows = session.execute(
        select(SimulatedTrade, Asset)
        .join(Asset, Asset.id == SimulatedTrade.asset_id)
        .where(SimulatedTrade.portfolio_id == portfolio_id)
        .order_by(SimulatedTrade.executed_at.desc(), SimulatedTrade.id.desc())
        .limit(20)
    ).all()
    return [
        {
            "id": trade.id,
            "symbol": asset.symbol,
            "side": trade.side,
            "quantity": float(trade.quantity),
            "price_brl": float(trade.price_brl),
            "notional_brl": float(trade.notional_brl),
            "executed_at": trade.executed_at,
        }
        for trade, asset in rows
    ]
