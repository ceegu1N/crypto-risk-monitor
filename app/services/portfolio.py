from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.portfolio import PortfolioMetrics, Position, calculate_portfolio
from app.models import Asset, PortfolioPosition, RiskSnapshot


def calculate_saved_portfolio(session: Session) -> PortfolioMetrics:
    rows = session.execute(
        select(PortfolioPosition, Asset)
        .join(Asset, Asset.id == PortfolioPosition.asset_id)
        .order_by(Asset.symbol)
    ).all()
    if not rows:
        return calculate_portfolio([], {}, {})

    positions: list[Position] = []
    prices: dict[str, float] = {}
    volatilities: dict[str, float | None] = {}
    for stored, asset in rows:
        snapshot = session.scalar(
            select(RiskSnapshot)
            .where(RiskSnapshot.asset_id == asset.id)
            .order_by(RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc())
            .limit(1)
        )
        if snapshot is None:
            raise ValueError(f"market price unavailable for {asset.symbol}")
        positions.append(
            Position(
                asset.symbol,
                float(stored.quantity),
                float(stored.cost_basis_brl) if stored.cost_basis_brl is not None else None,
            )
        )
        prices[asset.symbol] = float(snapshot.last_price)
        volatilities[asset.symbol] = (
            float(snapshot.volatility_24h_pct)
            if snapshot.volatility_24h_pct is not None
            else None
        )
    return calculate_portfolio(positions, prices, volatilities)


def upsert_position(
    session: Session,
    symbol: str,
    *,
    quantity: Decimal,
    cost_basis_brl: Decimal | None,
) -> PortfolioPosition:
    asset = session.scalar(select(Asset).where(Asset.symbol == symbol.strip().upper()))
    if asset is None:
        raise ValueError(f"unknown asset: {symbol}")
    position = session.scalar(
        select(PortfolioPosition).where(PortfolioPosition.asset_id == asset.id)
    )
    if position is None:
        position = PortfolioPosition(asset_id=asset.id, quantity=quantity)
        session.add(position)
    position.quantity = quantity
    position.cost_basis_brl = cost_basis_brl
    session.flush()
    return position


def remove_position(session: Session, symbol: str) -> bool:
    asset_id = session.scalar(select(Asset.id).where(Asset.symbol == symbol.strip().upper()))
    if asset_id is None:
        return False
    result = session.execute(
        delete(PortfolioPosition).where(PortfolioPosition.asset_id == asset_id)
    )
    return bool(result.rowcount)
