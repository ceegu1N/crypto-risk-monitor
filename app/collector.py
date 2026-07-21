import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Protocol, cast

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import get_session_factory
from app.domain.rules import (
    RiskRule,
    RuleOperator,
    RuleScope,
    Severity,
    evaluate_rules,
)
from app.integrations.binance import BinanceClient, CandleData
from app.integrations.discord import DiscordNotifier
from app.models import AlertRule, Asset, Candle, RiskSnapshot
from app.services.alerts import AlertService
from app.services.ingestion import IngestionService
from app.services.portfolio import calculate_saved_portfolio

COLLECTOR_LOCK_KEY = 4_319_775_013
INTERVAL_MINUTES = 15


class MarketClient(Protocol):
    def fetch_candles(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str = "15m",
    ) -> list[CandleData]: ...


@dataclass(frozen=True, slots=True)
class CollectorResult:
    lock_acquired: bool
    assets_processed: int
    candles_processed: int
    errors: tuple[str, ...]


CollectorCallable = Callable[[Settings], CollectorResult]
WaitCallable = Callable[[float], None]
ReportCallable = Callable[[CollectorResult], None]


def completed_candle_boundary(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a timezone")
    current = current.astimezone(UTC)
    minute = current.minute - (current.minute % INTERVAL_MINUTES)
    return current.replace(minute=minute, second=0, microsecond=0)


def collect_once(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session] | None = None,
    market_client: MarketClient | None = None,
    now: datetime | None = None,
) -> CollectorResult:
    factory = session_factory or get_session_factory()
    boundary = completed_candle_boundary(now)
    owns_client = market_client is None
    client = market_client or BinanceClient(base_url=str(settings.binance_base_url))

    try:
        with factory() as lock_session:
            acquired = bool(
                lock_session.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": COLLECTOR_LOCK_KEY},
                )
            )
            if not acquired:
                return CollectorResult(False, 0, 0, ())
            try:
                return _collect_assets(settings, factory, client, boundary)
            finally:
                lock_session.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": COLLECTOR_LOCK_KEY},
                )
    finally:
        if owns_client and isinstance(client, BinanceClient):
            client.close()


def run_collector_loop(
    settings: Settings,
    *,
    collect: CollectorCallable = collect_once,
    wait: WaitCallable = sleep,
    report: ReportCallable | None = None,
) -> None:
    reporter = report or report_result
    while True:
        result = collect(settings)
        reporter(result)
        wait(settings.collector_interval_seconds)


def report_result(result: CollectorResult) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    if not result.lock_acquired:
        print(f"[{timestamp}] ciclo ignorado: outro coletor esta ativo", flush=True)
        return
    print(
        f"[{timestamp}] ativos={result.assets_processed} "
        f"candles={result.candles_processed} erros={len(result.errors)}",
        flush=True,
    )
    for error in result.errors:
        print(f"  - {error}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coletor do Crypto Risk Monitor")
    parser.add_argument(
        "--once",
        action="store_true",
        help="executa um unico ciclo e encerra",
    )
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.once:
        result = collect_once(settings)
        report_result(result)
        return 1 if result.errors else 0

    try:
        run_collector_loop(settings)
    except KeyboardInterrupt:
        print("\nColetor encerrado.", flush=True)
    return 0


def _collect_assets(
    settings: Settings,
    factory: sessionmaker[Session],
    client: MarketClient,
    boundary: datetime,
) -> CollectorResult:
    ingestion = IngestionService(factory)
    assets_processed = 0
    candles_processed = 0
    errors: list[str] = []

    for symbol in settings.symbols:
        try:
            start = _collection_start(factory, symbol, boundary, settings.bootstrap_days)
            candles = client.fetch_candles(
                symbol,
                start=start,
                end=boundary,
                interval=settings.candle_interval,
            )
            result = ingestion.ingest_asset(symbol, candles, calculated_at=boundary)
            assets_processed += 1
            candles_processed += result.candles_processed
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

    try:
        _evaluate_alerts(settings, factory, boundary)
    except Exception as exc:
        errors.append(f"alerts: {type(exc).__name__}: {exc}")

    return CollectorResult(True, assets_processed, candles_processed, tuple(errors))


def _collection_start(
    factory: sessionmaker[Session],
    symbol: str,
    boundary: datetime,
    bootstrap_days: int,
) -> datetime:
    with factory() as session:
        latest = session.scalar(
            select(func.max(Candle.opened_at))
            .join(Asset, Asset.id == Candle.asset_id)
            .where(Asset.symbol == symbol)
        )
    return latest if latest is not None else boundary - timedelta(days=bootstrap_days)


def _evaluate_alerts(
    settings: Settings,
    factory: sessionmaker[Session],
    observed_at: datetime,
) -> None:
    rules = _enabled_rules(factory, settings.risk_profile)
    webhook_url = str(settings.discord_webhook_url) if settings.discord_webhook_url else None
    notifier = DiscordNotifier(webhook_url) if webhook_url else None
    service = AlertService(factory, notifier)
    try:
        market_rules = tuple(rule for rule in rules if rule.scope == "market")
        for symbol in settings.symbols:
            metrics = _latest_market_metrics(factory, symbol)
            if metrics is None:
                continue
            evaluated_codes = frozenset(
                rule.code for rule in market_rules if metrics.get(rule.metric) is not None
            )
            events = evaluate_rules(metrics, market_rules, scope="market")
            service.sync(
                profile=settings.risk_profile,
                scope="market",
                asset_symbol=symbol,
                events=events,
                evaluated_codes=evaluated_codes,
                observed_at=observed_at,
            )

        portfolio_rules = tuple(rule for rule in rules if rule.scope == "portfolio")
        portfolio_metrics = _portfolio_metrics(factory)
        evaluated_codes = frozenset(rule.code for rule in portfolio_rules)
        events = evaluate_rules(portfolio_metrics, portfolio_rules, scope="portfolio")
        service.sync(
            profile=settings.risk_profile,
            scope="portfolio",
            asset_symbol=None,
            events=events,
            evaluated_codes=evaluated_codes,
            observed_at=observed_at,
        )
    finally:
        if notifier is not None:
            notifier.close()


def _enabled_rules(
    factory: sessionmaker[Session],
    profile: str,
) -> tuple[RiskRule, ...]:
    with factory() as session:
        stored_rules = tuple(
            session.scalars(
                select(AlertRule)
                .where(AlertRule.profile == profile, AlertRule.enabled.is_(True))
                .order_by(AlertRule.id)
            )
        )
    return tuple(
        RiskRule(
            code=rule.code,
            label=rule.label,
            metric=rule.metric,
            operator=cast(RuleOperator, rule.operator),
            threshold=float(rule.threshold),
            severity=cast(Severity, rule.severity),
            scope=cast(RuleScope, rule.scope),
            unit=rule.unit,
        )
        for rule in stored_rules
    )


def _latest_market_metrics(
    factory: sessionmaker[Session],
    symbol: str,
) -> dict[str, float | None] | None:
    with factory() as session:
        snapshot = session.scalar(
            select(RiskSnapshot)
            .join(Asset, Asset.id == RiskSnapshot.asset_id)
            .where(Asset.symbol == symbol)
            .order_by(RiskSnapshot.calculated_at.desc(), RiskSnapshot.id.desc())
            .limit(1)
        )
    if snapshot is None:
        return None
    return {
        "return_1h_pct": _optional_float(snapshot.return_1h_pct),
        "return_24h_pct": _optional_float(snapshot.return_24h_pct),
        "volatility_24h_pct": _optional_float(snapshot.volatility_24h_pct),
        "drawdown_7d_pct": _optional_float(snapshot.drawdown_7d_pct),
        "volume_ratio": _optional_float(snapshot.volume_ratio),
        "staleness_minutes": float(snapshot.staleness_minutes),
    }


def _portfolio_metrics(factory: sessionmaker[Session]) -> dict[str, float]:
    with factory() as session:
        metrics = calculate_saved_portfolio(session)
    return {
        "max_position_weight_pct": metrics.max_weight_pct,
        "volatile_asset_share_pct": metrics.volatile_asset_share_pct,
    }


def _optional_float(value: object | None) -> float | None:
    return float(value) if value is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
