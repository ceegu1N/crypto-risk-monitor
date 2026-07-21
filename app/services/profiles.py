from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Alert, AlertEvent, AlertRule, AppSetting

RiskProfile = Literal["conservative", "moderate", "aggressive", "custom"]
BUILT_IN_PROFILES = frozenset({"conservative", "moderate", "aggressive"})
RISK_PROFILES = BUILT_IN_PROFILES | {"custom"}
ACTIVE_PROFILE_KEY = "active_risk_profile"
CUSTOM_BASE_KEY = "custom_base_profile"


@dataclass(frozen=True, slots=True)
class RiskProfileState:
    profile: RiskProfile
    custom_base_profile: str | None


def get_risk_profile_state(
    session: Session,
    *,
    fallback: str = "moderate",
) -> RiskProfileState:
    safe_fallback = fallback if fallback in RISK_PROFILES else "moderate"
    active = session.get(AppSetting, ACTIVE_PROFILE_KEY)
    profile = active.value if active and active.value in RISK_PROFILES else safe_fallback
    base = session.get(AppSetting, CUSTOM_BASE_KEY)
    custom_base = base.value if base and base.value in BUILT_IN_PROFILES else None
    return RiskProfileState(cast(RiskProfile, profile), custom_base)


def get_active_risk_profile(
    factory: sessionmaker[Session],
    *,
    fallback: str = "moderate",
) -> RiskProfile:
    with factory() as session:
        return get_risk_profile_state(session, fallback=fallback).profile


def set_active_risk_profile(
    session: Session,
    profile: RiskProfile,
    *,
    fallback: str = "moderate",
) -> RiskProfileState:
    if profile not in RISK_PROFILES:
        raise ValueError(f"unknown risk profile: {profile}")
    if not session.scalar(select(AlertRule.id).where(AlertRule.profile == profile).limit(1)):
        raise ValueError(f"risk profile has no configured rules: {profile}")
    previous = get_risk_profile_state(session, fallback=fallback).profile
    _set_value(session, ACTIVE_PROFILE_KEY, profile)
    if previous != profile:
        _close_inactive_profile_alerts(session, profile)
    return get_risk_profile_state(session, fallback=fallback)


def customize_rule(
    session: Session,
    code: str,
    *,
    threshold: Decimal | None,
    enabled: bool | None,
    fallback: str = "moderate",
) -> AlertRule:
    state = get_risk_profile_state(session, fallback=fallback)
    source_profile = state.profile
    if source_profile != "custom":
        _copy_profile_rules(session, source_profile, "custom")
        _set_value(session, CUSTOM_BASE_KEY, source_profile)
        set_active_risk_profile(session, "custom", fallback=fallback)
    rule = session.scalar(
        select(AlertRule).where(AlertRule.profile == "custom", AlertRule.code == code)
    )
    if rule is None:
        raise ValueError(f"rule not found in active profile: {code}")
    if threshold is not None:
        rule.threshold = threshold
    if enabled is not None:
        rule.enabled = enabled
    session.flush()
    return rule


def reset_custom_profile(
    session: Session,
    *,
    fallback: str = "moderate",
) -> RiskProfileState:
    state = get_risk_profile_state(session, fallback=fallback)
    fallback_base = fallback if fallback in BUILT_IN_PROFILES else "moderate"
    base = state.custom_base_profile or fallback_base
    _copy_profile_rules(session, base, "custom")
    _set_value(session, CUSTOM_BASE_KEY, base)
    return set_active_risk_profile(session, "custom", fallback=fallback)


def _copy_profile_rules(session: Session, source: str, target: str) -> None:
    source_rules = list(
        session.scalars(select(AlertRule).where(AlertRule.profile == source).order_by(AlertRule.id))
    )
    target_by_code = {
        rule.code: rule
        for rule in session.scalars(select(AlertRule).where(AlertRule.profile == target))
    }
    if not source_rules:
        raise ValueError(f"risk profile has no configured rules: {source}")
    for source_rule in source_rules:
        target_rule = target_by_code.get(source_rule.code)
        if target_rule is None:
            raise ValueError(f"custom profile is missing rule: {source_rule.code}")
        target_rule.label = source_rule.label
        target_rule.metric = source_rule.metric
        target_rule.operator = source_rule.operator
        target_rule.threshold = Decimal(source_rule.threshold)
        target_rule.severity = source_rule.severity
        target_rule.scope = source_rule.scope
        target_rule.unit = source_rule.unit
        target_rule.enabled = source_rule.enabled
    session.flush()


def _set_value(session: Session, key: str, value: str) -> None:
    setting = session.get(AppSetting, key)
    if setting is None:
        session.add(AppSetting(key=key, value=value))
    else:
        setting.value = value
    session.flush()


def _close_inactive_profile_alerts(session: Session, active_profile: str) -> None:
    observed_at = datetime.now(UTC)
    rows = session.scalars(
        select(Alert)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .where(Alert.condition_active.is_(True), AlertRule.profile != active_profile)
    )
    for alert in rows:
        previous_status = alert.status
        alert.condition_active = False
        alert.status = "resolved"
        alert.resolved_at = observed_at
        session.add(
            AlertEvent(
                alert_id=alert.id,
                action="profile_changed",
                from_status=previous_status,
                to_status="resolved",
                actor="operator",
                details={"active_profile": active_profile},
            )
        )
