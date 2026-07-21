import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_operator
from app.api.schemas import AlertTransitionRequest, LoginRequest, PositionUpsert, RuleUpdate
from app.models import (
    Alert,
    AlertRule,
    Asset,
    Candle,
    IngestionRun,
    RiskSnapshot,
)
from app.services.alerts import AlertService, InvalidAlertTransition
from app.services.portfolio import (
    calculate_saved_portfolio,
    remove_position,
    upsert_position,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@router.get("/assets")
def assets(session: SessionDep) -> list[dict[str, object]]:
    return [
        {
            "symbol": asset.symbol,
            "base_asset": asset.base_asset,
            "quote_asset": asset.quote_asset,
            "display_name": asset.display_name,
            "active": asset.active,
        }
        for asset in session.scalars(select(Asset).order_by(Asset.symbol))
    ]


@router.get("/market")
def market(session: SessionDep) -> list[dict[str, object]]:
    asset_rows = list(
        session.scalars(select(Asset).where(Asset.active.is_(True)).order_by(Asset.id))
    )
    snapshot_by_asset: dict[int, RiskSnapshot] = {}
    for snapshot in session.scalars(
        select(RiskSnapshot).order_by(
            RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc()
        )
    ):
        snapshot_by_asset.setdefault(snapshot.asset_id, snapshot)
    return [
        _market_payload(asset, snapshot_by_asset.get(asset.id))
        for asset in asset_rows
    ]


@router.get("/assets/{symbol}/candles")
def candles(
    symbol: str,
    session: SessionDep,
    period: Literal["24h", "7d"] = "24h",
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[dict[str, object]]:
    asset = session.scalar(select(Asset).where(Asset.symbol == symbol.strip().upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    since = datetime.now(UTC) - (timedelta(days=1) if period == "24h" else timedelta(days=7))
    rows = list(
        session.scalars(
            select(Candle)
            .where(Candle.asset_id == asset.id, Candle.opened_at >= since)
            .order_by(Candle.opened_at.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return [
        {
            "opened_at": candle.opened_at,
            "open": float(candle.open_price),
            "high": float(candle.high_price),
            "low": float(candle.low_price),
            "close": float(candle.close_price),
            "volume": float(candle.volume),
        }
        for candle in rows
    ]


@router.get("/alerts")
def alerts(session: SessionDep) -> list[dict[str, object]]:
    rows = session.execute(
        select(Alert, AlertRule, Asset)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .outerjoin(Asset, Asset.id == Alert.asset_id)
        .order_by(Alert.last_triggered_at.desc())
    ).all()
    return [
        {
            "id": alert.id,
            "code": rule.code,
            "label": rule.label,
            "symbol": asset.symbol if asset else None,
            "status": alert.status,
            "condition_active": alert.condition_active,
            "severity": alert.severity,
            "observed": float(alert.observed_value),
            "threshold": float(alert.threshold),
            "message": alert.message,
            "first_triggered_at": alert.first_triggered_at,
            "last_triggered_at": alert.last_triggered_at,
        }
        for alert, rule, asset in rows
    ]


@router.get("/rules")
def rules(request: Request, session: SessionDep) -> list[dict[str, object]]:
    profile = request.app.state.settings.risk_profile
    return [
        _rule_payload(rule)
        for rule in session.scalars(
            select(AlertRule)
            .where(AlertRule.profile == profile)
            .order_by(AlertRule.scope, AlertRule.id)
        )
    ]


@router.get("/portfolio")
def portfolio(session: SessionDep) -> dict[str, object]:
    try:
        result = calculate_saved_portfolio(session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "total_value_brl": result.total_value_brl,
        "cost_basis_value_brl": result.cost_basis_value_brl,
        "pnl_brl": result.pnl_brl,
        "pnl_pct": result.pnl_pct,
        "max_weight_pct": result.max_weight_pct,
        "volatile_asset_share_pct": result.volatile_asset_share_pct,
        "risk_contribution_note": result.risk_contribution_note,
        "positions": [
            {
                "symbol": item.symbol,
                "quantity": item.quantity,
                "price_brl": item.price_brl,
                "current_value_brl": item.current_value_brl,
                "weight_pct": item.weight_pct,
                "cost_basis_brl": item.cost_basis_brl,
                "pnl_brl": item.pnl_brl,
                "pnl_pct": item.pnl_pct,
                "volatility_24h_pct": item.volatility_24h_pct,
                "risk_contribution": item.risk_contribution,
            }
            for item in result.positions
        ],
    }


@router.get("/system")
def system_status(session: SessionDep) -> dict[str, object]:
    latest_run = session.scalar(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1)
    )
    return {
        "latest_ingestion": (
            {
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "finished_at": latest_run.finished_at,
                "duration_ms": latest_run.duration_ms,
                "candles_received": latest_run.candles_received,
                "candles_upserted": latest_run.candles_upserted,
                "error_message": latest_run.error_message,
            }
            if latest_run
            else None
        )
    }


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request) -> dict[str, bool]:
    expected = request.app.state.settings.operator_password
    if not secrets.compare_digest(payload.password, expected):
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session.clear()
    request.session["operator"] = True
    return {"authenticated": True}


@router.get("/auth/session")
def auth_session(request: Request) -> dict[str, bool]:
    return {"authenticated": request.session.get("operator") is True}


@router.post("/auth/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"authenticated": False}


@router.put("/portfolio/positions/{symbol}", dependencies=[Depends(require_operator)])
def save_position(
    symbol: str,
    payload: PositionUpsert,
    session: SessionDep,
) -> dict[str, object]:
    try:
        position = upsert_position(
            session,
            symbol,
            quantity=payload.quantity,
            cost_basis_brl=payload.cost_basis_brl,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": position.id,
        "symbol": symbol.strip().upper(),
        "quantity": float(position.quantity),
        "cost_basis_brl": (
            float(position.cost_basis_brl) if position.cost_basis_brl is not None else None
        ),
    }


@router.delete("/portfolio/positions/{symbol}", dependencies=[Depends(require_operator)])
def delete_position(
    symbol: str,
    session: SessionDep,
) -> Response:
    removed = remove_position(session, symbol)
    session.commit()
    if not removed:
        raise HTTPException(status_code=404, detail="position not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/rules/{rule_id}", dependencies=[Depends(require_operator)])
def update_rule(
    rule_id: int,
    payload: RuleUpdate,
    session: SessionDep,
) -> dict[str, object]:
    rule = session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    session.commit()
    session.refresh(rule)
    return _rule_payload(rule)


@router.patch("/alerts/{alert_id}", dependencies=[Depends(require_operator)])
def update_alert(
    alert_id: int,
    payload: AlertTransitionRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, object]:
    service = AlertService(request.app.state.session_factory)
    try:
        service.transition(alert_id, payload.status, actor="operator")
    except ValueError as exc:
        status_code = 409 if isinstance(exc, InvalidAlertTransition) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    session.expire_all()
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return {"id": alert.id, "status": alert.status, "condition_active": alert.condition_active}


def _market_payload(asset: Asset, snapshot: RiskSnapshot | None) -> dict[str, object]:
    return {
        "symbol": asset.symbol,
        "display_name": asset.display_name,
        "price_brl": _metric(snapshot.last_price if snapshot else None),
        "return_1h_pct": _metric(snapshot.return_1h_pct if snapshot else None),
        "return_24h_pct": _metric(snapshot.return_24h_pct if snapshot else None),
        "volatility_24h_pct": _metric(snapshot.volatility_24h_pct if snapshot else None),
        "drawdown_7d_pct": _metric(snapshot.drawdown_7d_pct if snapshot else None),
        "volume_ratio": _metric(snapshot.volume_ratio if snapshot else None),
        "staleness_minutes": _metric(snapshot.staleness_minutes if snapshot else None),
        "calculated_at": snapshot.calculated_at if snapshot else None,
    }


def _rule_payload(rule: AlertRule) -> dict[str, object]:
    return {
        "id": rule.id,
        "profile": rule.profile,
        "code": rule.code,
        "label": rule.label,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": float(rule.threshold),
        "severity": rule.severity,
        "scope": rule.scope,
        "unit": rule.unit,
        "enabled": rule.enabled,
    }


def _metric(value: object | None) -> float | None:
    return float(value) if value is not None else None
