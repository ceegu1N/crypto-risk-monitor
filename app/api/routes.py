import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_operator
from app.api.schemas import (
    AlertTransitionRequest,
    LoginRequest,
    PositionUpsert,
    RiskProfileUpdate,
    RuleUpdate,
)
from app.models import (
    Alert,
    AlertEvent,
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
from app.services.profiles import (
    customize_rule,
    get_risk_profile_state,
    reset_custom_profile,
    set_active_risk_profile,
)
from app.services.risk import effective_staleness_minutes

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
def market(request: Request, session: SessionDep) -> list[dict[str, object]]:
    observed_at = datetime.now(UTC)
    asset_rows = list(
        session.scalars(select(Asset).where(Asset.active.is_(True)).order_by(Asset.id))
    )
    snapshot_by_asset = _latest_snapshots(session)
    profile = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    ).profile
    reasons_by_asset = _active_risk_reasons(
        session,
        profile=profile,
        asset_ids={asset.id for asset in asset_rows},
    )
    return [
        _market_payload(
            asset,
            snapshot_by_asset.get(asset.id),
            observed_at=observed_at,
            reasons=reasons_by_asset.get(asset.id, []),
        )
        for asset in asset_rows
    ]


@router.get("/assets/{symbol}")
def asset_detail(symbol: str, request: Request, session: SessionDep) -> dict[str, object]:
    asset = _find_asset(session, symbol)
    snapshot = _latest_snapshot(session, asset.id)
    profile = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    ).profile
    reasons = _active_risk_reasons(session, profile=profile, asset_ids={asset.id}).get(
        asset.id,
        [],
    )
    return _market_payload(
        asset,
        snapshot,
        observed_at=datetime.now(UTC),
        reasons=reasons,
    )


@router.get("/assets/{symbol}/risk")
def asset_risk(symbol: str, request: Request, session: SessionDep) -> dict[str, object]:
    asset = _find_asset(session, symbol)
    snapshot = _latest_snapshot(session, asset.id)
    profile = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    ).profile
    reasons = _active_risk_reasons(session, profile=profile, asset_ids={asset.id}).get(
        asset.id,
        [],
    )
    payload = _market_payload(
        asset,
        snapshot,
        observed_at=datetime.now(UTC),
        reasons=reasons,
    )
    return {
        "symbol": asset.symbol,
        "profile": profile,
        "risk_level": payload["risk_level"],
        "risk_reasons": payload["risk_reasons"],
        "metrics": {
            key: payload[key]
            for key in (
                "return_1h_pct",
                "return_24h_pct",
                "volatility_24h_pct",
                "drawdown_7d_pct",
                "volume_ratio",
                "staleness_minutes",
            )
        },
        "calculated_at": payload["calculated_at"],
    }


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


@router.get("/alerts/{alert_id}/events")
def alert_events(alert_id: int, session: SessionDep) -> list[dict[str, object]]:
    if session.get(Alert, alert_id) is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return [
        {
            "id": event.id,
            "action": event.action,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "actor": event.actor,
            "details": event.details,
            "created_at": event.created_at,
        }
        for event in session.scalars(
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.created_at, AlertEvent.id)
        )
    ]


@router.get("/rules")
def rules(request: Request, session: SessionDep) -> list[dict[str, object]]:
    profile = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    ).profile
    return [
        _rule_payload(rule)
        for rule in session.scalars(
            select(AlertRule)
            .where(AlertRule.profile == profile)
            .order_by(AlertRule.scope, AlertRule.id)
        )
    ]


@router.get("/settings/risk-profile")
def risk_profile(request: Request, session: SessionDep) -> dict[str, str | None]:
    state = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    )
    return {
        "profile": state.profile,
        "custom_base_profile": state.custom_base_profile,
    }


@router.get("/portfolio")
def portfolio(request: Request, session: SessionDep) -> dict[str, object]:
    try:
        result = calculate_saved_portfolio(session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    profile = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    ).profile
    reasons = _active_portfolio_reasons(session, profile=profile)
    return {
        "total_value_brl": result.total_value_brl,
        "cost_basis_value_brl": result.cost_basis_value_brl,
        "pnl_brl": result.pnl_brl,
        "pnl_pct": result.pnl_pct,
        "return_24h_pct": result.return_24h_pct,
        "max_weight_pct": result.max_weight_pct,
        "volatile_asset_share_pct": result.volatile_asset_share_pct,
        "risk_contribution_note": result.risk_contribution_note,
        "risk_level": _risk_level(reasons),
        "risk_reasons": reasons,
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


@router.get("/system/runs")
def system_runs(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    return [
        _run_payload(run)
        for run in session.scalars(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        )
    ]


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
    request: Request,
    session: SessionDep,
) -> dict[str, object]:
    requested_rule = session.get(AlertRule, rule_id)
    if requested_rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    state = get_risk_profile_state(
        session,
        fallback=request.app.state.settings.risk_profile,
    )
    if requested_rule.profile != state.profile:
        raise HTTPException(status_code=409, detail="rule is not part of the active profile")
    rule = customize_rule(
        session,
        requested_rule.code,
        threshold=payload.threshold,
        enabled=payload.enabled,
        fallback=request.app.state.settings.risk_profile,
    )
    session.commit()
    session.refresh(rule)
    return _rule_payload(rule)


@router.put(
    "/settings/risk-profile",
    dependencies=[Depends(require_operator)],
)
def change_risk_profile(
    payload: RiskProfileUpdate,
    request: Request,
    session: SessionDep,
) -> dict[str, str | None]:
    try:
        state = set_active_risk_profile(
            session,
            payload.profile,
            fallback=request.app.state.settings.risk_profile,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "profile": state.profile,
        "custom_base_profile": state.custom_base_profile,
    }


@router.put(
    "/settings/rules/{rule_code}",
    dependencies=[Depends(require_operator)],
)
def change_active_rule(
    rule_code: str,
    payload: RuleUpdate,
    request: Request,
    session: SessionDep,
) -> dict[str, object]:
    try:
        rule = customize_rule(
            session,
            rule_code,
            threshold=payload.threshold,
            enabled=payload.enabled,
            fallback=request.app.state.settings.risk_profile,
        )
        session.commit()
        session.refresh(rule)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _rule_payload(rule)


@router.post(
    "/settings/risk-profile/reset",
    dependencies=[Depends(require_operator)],
)
def reset_risk_profile(
    request: Request,
    session: SessionDep,
) -> dict[str, str | None]:
    try:
        state = reset_custom_profile(
            session,
            fallback=request.app.state.settings.risk_profile,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "profile": state.profile,
        "custom_base_profile": state.custom_base_profile,
    }


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


def _market_payload(
    asset: Asset,
    snapshot: RiskSnapshot | None,
    *,
    observed_at: datetime,
    reasons: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    active_reasons = reasons or []
    return {
        "symbol": asset.symbol,
        "display_name": asset.display_name,
        "price_brl": _metric(snapshot.last_price if snapshot else None),
        "return_1h_pct": _metric(snapshot.return_1h_pct if snapshot else None),
        "return_24h_pct": _metric(snapshot.return_24h_pct if snapshot else None),
        "volatility_24h_pct": _metric(snapshot.volatility_24h_pct if snapshot else None),
        "drawdown_7d_pct": _metric(snapshot.drawdown_7d_pct if snapshot else None),
        "volume_ratio": _metric(snapshot.volume_ratio if snapshot else None),
        "staleness_minutes": (
            effective_staleness_minutes(snapshot, observed_at=observed_at) if snapshot else None
        ),
        "calculated_at": snapshot.calculated_at if snapshot else None,
        "risk_level": _risk_level(active_reasons),
        "risk_reasons": active_reasons,
    }


def _find_asset(session: Session, symbol: str) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.symbol == symbol.strip().upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


def _latest_snapshot(session: Session, asset_id: int) -> RiskSnapshot | None:
    return session.scalar(
        select(RiskSnapshot)
        .where(RiskSnapshot.asset_id == asset_id)
        .order_by(RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc())
        .limit(1)
    )


def _latest_snapshots(session: Session) -> dict[int, RiskSnapshot]:
    ranked = select(
        RiskSnapshot.id.label("snapshot_id"),
        func.row_number()
        .over(
            partition_by=RiskSnapshot.asset_id,
            order_by=(RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc()),
        )
        .label("row_number"),
    ).subquery()
    rows = session.scalars(
        select(RiskSnapshot)
        .join(ranked, ranked.c.snapshot_id == RiskSnapshot.id)
        .where(ranked.c.row_number == 1)
    )
    return {snapshot.asset_id: snapshot for snapshot in rows}


def _active_risk_reasons(
    session: Session,
    *,
    profile: str,
    asset_ids: set[int],
) -> dict[int, list[dict[str, object]]]:
    if not asset_ids:
        return {}
    grouped: dict[int, list[dict[str, object]]] = {}
    rows = session.execute(
        select(Alert, AlertRule)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .where(
            Alert.condition_active.is_(True),
            AlertRule.profile == profile,
            Alert.asset_id.in_(asset_ids),
        )
        .order_by(Alert.asset_id, Alert.last_triggered_at.desc())
    )
    for alert, rule in rows:
        if alert.asset_id is None:
            continue
        grouped.setdefault(alert.asset_id, []).append(_risk_reason_payload(alert, rule))
    return grouped


def _active_portfolio_reasons(
    session: Session,
    *,
    profile: str,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(Alert, AlertRule)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .where(
            Alert.condition_active.is_(True),
            AlertRule.profile == profile,
            Alert.asset_id.is_(None),
        )
        .order_by(Alert.last_triggered_at.desc())
    )
    return [_risk_reason_payload(alert, rule) for alert, rule in rows]


def _risk_reason_payload(alert: Alert, rule: AlertRule) -> dict[str, object]:
    return {
        "code": rule.code,
        "label": rule.label,
        "severity": alert.severity,
        "message": alert.message,
        "observed": float(alert.observed_value),
        "threshold": float(alert.threshold),
    }


def _risk_level(reasons: list[dict[str, object]]) -> str:
    ranking = {"normal": 0, "warning": 1, "high": 2, "critical": 3}
    return max(
        (str(reason["severity"]) for reason in reasons),
        key=lambda severity: ranking.get(severity, 0),
        default="normal",
    )


def _run_payload(run: IngestionRun) -> dict[str, object]:
    return {
        "id": run.id,
        "status": run.status,
        "source": run.source,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "candles_received": run.candles_received,
        "candles_upserted": run.candles_upserted,
        "error_message": run.error_message,
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
