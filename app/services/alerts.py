import logging
from collections.abc import Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.rules import RuleEvent, RuleOperator, RuleScope
from app.integrations.discord import AlertNotification
from app.models import Alert, AlertEvent, AlertRule, Asset

logger = logging.getLogger(__name__)
AlertStatus = Literal["new", "acknowledged", "resolved", "dismissed"]


class AlertNotifier(Protocol):
    def notify(self, notification: AlertNotification) -> bool: ...


class InvalidAlertTransition(ValueError):
    """Raised when an operator requests an invalid alert state transition."""


@dataclass(frozen=True, slots=True)
class AlertSyncResult:
    alert_ids: tuple[int, ...]
    notifications_attempted: int


_OPERATOR_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"acknowledged", "resolved", "dismissed"}),
    "acknowledged": frozenset({"resolved", "dismissed"}),
    "resolved": frozenset(),
    "dismissed": frozenset(),
}


def ensure_operator_transition(current: str, target: str) -> None:
    if target not in _OPERATOR_TRANSITIONS.get(current, frozenset()):
        raise InvalidAlertTransition(f"cannot move alert from {current} to {target}")


def observed_value_worsened(operator: RuleOperator, *, previous: float, current: float) -> bool:
    return current > previous if operator == "gte" else current < previous


class AlertService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier: AlertNotifier | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier

    def sync(
        self,
        *,
        profile: str,
        scope: RuleScope,
        asset_symbol: str | None,
        events: Sequence[RuleEvent],
        evaluated_codes: Set[str],
        observed_at: datetime,
    ) -> AlertSyncResult:
        event_by_code = {event.code: event for event in events}
        if len(event_by_code) != len(events):
            raise ValueError("duplicate rule events in the same evaluation")
        notifications: list[AlertNotification] = []
        alert_ids: list[int] = []

        with self.session_factory.begin() as session:
            asset = self._find_asset(session, asset_symbol)
            rules = list(
                session.scalars(
                    select(AlertRule).where(
                        AlertRule.profile == profile,
                        AlertRule.scope == scope,
                        AlertRule.code.in_(evaluated_codes),
                    )
                )
            )
            rule_by_code = {rule.code: rule for rule in rules}
            missing = set(event_by_code) - set(rule_by_code)
            if missing:
                raise ValueError(f"rules not configured in database: {sorted(missing)}")

            existing = self._existing_alerts(session, profile, evaluated_codes, asset_symbol)
            for code, event in event_by_code.items():
                rule = rule_by_code[code]
                key = _dedupe_key(profile, code, asset_symbol)
                alert = existing.get(key)
                if alert is None:
                    alert = _new_alert(rule, asset, key, event, observed_at)
                    session.add(alert)
                    session.flush()
                    session.add(_alert_event(alert, "triggered", None, "new", observed_at))
                    action = "triggered"
                else:
                    action = self._refresh_alert(session, alert, rule, event, observed_at)
                alert_ids.append(alert.id)
                if action in {"triggered", "reopened", "aggravated"}:
                    notifications.append(_notification(alert, rule, asset_symbol, observed_at))

            inactive_codes = set(evaluated_codes) - set(event_by_code)
            for code in inactive_codes:
                alert = existing.get(_dedupe_key(profile, code, asset_symbol))
                if alert is None or not alert.condition_active:
                    continue
                previous_status = alert.status
                alert.condition_active = False
                if alert.status in {"new", "acknowledged"}:
                    alert.status = "resolved"
                    alert.resolved_at = observed_at
                    action = "resolved"
                else:
                    action = "condition_cleared"
                session.add(
                    _alert_event(alert, action, previous_status, alert.status, observed_at)
                )
                alert_ids.append(alert.id)

        attempted = self._notify_without_breaking_monitoring(notifications)
        return AlertSyncResult(tuple(sorted(set(alert_ids))), attempted)

    def transition(self, alert_id: int, target: AlertStatus, *, actor: str) -> None:
        with self.session_factory.begin() as session:
            alert = session.get(Alert, alert_id)
            if alert is None:
                raise ValueError(f"alert {alert_id} not found")
            previous_status = alert.status
            ensure_operator_transition(previous_status, target)
            alert.status = target
            if target == "resolved":
                alert.resolved_at = datetime.now(UTC)
            session.add(
                _alert_event(
                    alert,
                    target,
                    previous_status,
                    target,
                    datetime.now(UTC),
                    actor=actor,
                )
            )

    def _find_asset(self, session: Session, symbol: str | None) -> Asset | None:
        if symbol is None:
            return None
        asset = session.scalar(select(Asset).where(Asset.symbol == symbol.strip().upper()))
        if asset is None:
            raise ValueError(f"unknown asset: {symbol}")
        return asset

    def _existing_alerts(
        self,
        session: Session,
        profile: str,
        codes: Set[str],
        asset_symbol: str | None,
    ) -> dict[str, Alert]:
        keys = [_dedupe_key(profile, code, asset_symbol) for code in codes]
        if not keys:
            return {}
        return {
            alert.dedupe_key: alert
            for alert in session.scalars(select(Alert).where(Alert.dedupe_key.in_(keys)))
        }

    def _refresh_alert(
        self,
        session: Session,
        alert: Alert,
        rule: AlertRule,
        event: RuleEvent,
        observed_at: datetime,
    ) -> str:
        previous_status = alert.status
        previous_value = float(alert.observed_value)
        if alert.status in {"resolved", "dismissed"}:
            alert.status = "new"
            alert.resolved_at = None
            action = "reopened"
        elif observed_value_worsened(
            rule.operator, previous=previous_value, current=event.observed
        ):
            action = "aggravated"
        else:
            action = "repeated"
        alert.condition_active = True
        alert.observed_value = Decimal(str(event.observed))
        alert.threshold = Decimal(str(event.threshold))
        alert.severity = event.severity
        alert.message = event.message
        alert.last_triggered_at = observed_at
        session.add(_alert_event(alert, action, previous_status, alert.status, observed_at))
        return action

    def _notify_without_breaking_monitoring(
        self, notifications: Sequence[AlertNotification]
    ) -> int:
        if self.notifier is None:
            return 0
        attempted = 0
        for notification in notifications:
            attempted += 1
            try:
                self.notifier.notify(notification)
            except Exception:
                logger.exception("Discord notification failed for rule %s", notification.code)
        return attempted


def _new_alert(
    rule: AlertRule,
    asset: Asset | None,
    key: str,
    event: RuleEvent,
    observed_at: datetime,
) -> Alert:
    return Alert(
        rule_id=rule.id,
        asset_id=asset.id if asset else None,
        dedupe_key=key,
        status="new",
        condition_active=True,
        severity=event.severity,
        observed_value=Decimal(str(event.observed)),
        threshold=Decimal(str(event.threshold)),
        message=event.message,
        first_triggered_at=observed_at,
        last_triggered_at=observed_at,
    )


def _alert_event(
    alert: Alert,
    action: str,
    from_status: str | None,
    to_status: str,
    observed_at: datetime,
    *,
    actor: str = "system",
) -> AlertEvent:
    return AlertEvent(
        alert_id=alert.id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        details={"observed_at": observed_at.isoformat()},
    )


def _notification(
    alert: Alert,
    rule: AlertRule,
    asset_symbol: str | None,
    observed_at: datetime,
) -> AlertNotification:
    return AlertNotification(
        code=rule.code,
        label=rule.label,
        severity=alert.severity,
        symbol=asset_symbol,
        message=alert.message,
        observed_at=observed_at,
    )


def _dedupe_key(profile: str, code: str, asset_symbol: str | None) -> str:
    subject = asset_symbol.strip().upper() if asset_symbol else "portfolio"
    return f"{profile}:{code}:{subject}"
