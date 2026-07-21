from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

RuleOperator = Literal["gte", "lte"]
RuleScope = Literal["market", "portfolio", "system"]
RiskProfile = Literal["conservative", "moderate", "aggressive"]
Severity = Literal["warning", "high", "critical"]


@dataclass(frozen=True, slots=True)
class RiskRule:
    code: str
    label: str
    metric: str
    operator: RuleOperator
    threshold: float
    severity: Severity
    scope: RuleScope
    unit: str


@dataclass(frozen=True, slots=True)
class RuleEvent:
    code: str
    label: str
    metric: str
    operator: RuleOperator
    observed: float
    threshold: float
    severity: Severity
    scope: RuleScope
    message: str


def rules_for_profile(profile: str) -> tuple[RiskRule, ...]:
    try:
        return _PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown risk profile: {profile}") from exc


def evaluate_market_rules(
    metrics: Mapping[str, float | None],
    rules: Sequence[RiskRule],
) -> list[RuleEvent]:
    return evaluate_rules(metrics, rules, scope="market")


def evaluate_rules(
    metrics: Mapping[str, float | None],
    rules: Sequence[RiskRule],
    *,
    scope: RuleScope,
) -> list[RuleEvent]:
    events: list[RuleEvent] = []
    for rule in rules:
        if rule.scope != scope:
            continue
        raw_value = metrics.get(rule.metric)
        if raw_value is None:
            continue
        observed = float(raw_value)
        if not isfinite(observed) or not _matches(rule.operator, observed, rule.threshold):
            continue
        events.append(
            RuleEvent(
                code=rule.code,
                label=rule.label,
                metric=rule.metric,
                operator=rule.operator,
                observed=observed,
                threshold=rule.threshold,
                severity=rule.severity,
                scope=rule.scope,
                message=_event_message(rule, observed),
            )
        )
    return events


def _matches(operator: RuleOperator, observed: float, threshold: float) -> bool:
    if operator == "gte":
        return observed >= threshold
    return observed <= threshold


def _event_message(rule: RiskRule, observed: float) -> str:
    comparison = "maior ou igual a" if rule.operator == "gte" else "menor ou igual a"
    return (
        f"{rule.label}: valor observado {_format_value(observed, rule.unit)}, "
        f"limite {comparison} {_format_value(rule.threshold, rule.unit)}."
    )


def _format_value(value: float, unit: str) -> str:
    formatted = f"{value:.2f}".replace(".", ",")
    if unit == "%":
        return f"{formatted}%"
    if unit == "x":
        return f"{formatted}x"
    if unit == "min":
        return f"{formatted} min"
    return formatted


def _profile_rules(
    *,
    price_drop: float,
    volatility: float,
    volume_ratio: float,
    stale_minutes: float,
    max_position: float,
    volatile_share: float,
) -> tuple[RiskRule, ...]:
    return (
        RiskRule(
            "price_drop_24h",
            "Queda em 24 horas",
            "return_24h_pct",
            "lte",
            price_drop,
            "high",
            "market",
            "%",
        ),
        RiskRule(
            "volatility_24h",
            "Volatilidade em 24 horas",
            "volatility_24h_pct",
            "gte",
            volatility,
            "warning",
            "market",
            "%",
        ),
        RiskRule(
            "volume_spike",
            "Pico de volume",
            "volume_ratio",
            "gte",
            volume_ratio,
            "warning",
            "market",
            "x",
        ),
        RiskRule(
            "stale_market_data",
            "Dados de mercado atrasados",
            "staleness_minutes",
            "gte",
            stale_minutes,
            "critical",
            "market",
            "min",
        ),
        RiskRule(
            "portfolio_concentration",
            "Concentração do portfólio",
            "max_position_weight_pct",
            "gte",
            max_position,
            "high",
            "portfolio",
            "%",
        ),
        RiskRule(
            "volatile_asset_share",
            "Exposição a ativos voláteis",
            "volatile_asset_share_pct",
            "gte",
            volatile_share,
            "warning",
            "portfolio",
            "%",
        ),
    )


_PROFILES: dict[str, tuple[RiskRule, ...]] = {
    "conservative": _profile_rules(
        price_drop=-3.0,
        volatility=3.0,
        volume_ratio=2.0,
        stale_minutes=30.0,
        max_position=50.0,
        volatile_share=80.0,
    ),
    "moderate": _profile_rules(
        price_drop=-5.0,
        volatility=4.0,
        volume_ratio=2.5,
        stale_minutes=45.0,
        max_position=60.0,
        volatile_share=90.0,
    ),
    "aggressive": _profile_rules(
        price_drop=-8.0,
        volatility=6.0,
        volume_ratio=4.0,
        stale_minutes=90.0,
        max_position=75.0,
        volatile_share=95.0,
    ),
}
