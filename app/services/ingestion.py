from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.integrations.binance import CandleData
from app.models import Asset, Candle, IngestionRun
from app.services.risk import create_risk_snapshot


class IngestionError(RuntimeError):
    """Raised after an ingestion batch is rolled back and its failure is recorded."""


_UPSERT_BATCH_SIZE = 5_000


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: int
    symbol: str
    candles_processed: int
    risk_snapshot_id: int | None


class IngestionService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def ingest_asset(
        self,
        symbol: str,
        candles: Sequence[CandleData],
        *,
        calculated_at: datetime | None = None,
    ) -> IngestionResult:
        normalized_symbol = symbol.strip().upper()
        started_at = datetime.now(UTC)
        clock_started = perf_counter()
        run_id = self._start_run(normalized_symbol, started_at, len(candles))
        try:
            _validate_batch(normalized_symbol, candles)
            with self.session_factory.begin() as session:
                asset = session.scalar(select(Asset).where(Asset.symbol == normalized_symbol))
                if asset is None:
                    raise ValueError(f"unknown asset: {normalized_symbol}")
                if candles:
                    _upsert_candles(session, asset.id, candles)
                snapshot = create_risk_snapshot(
                    session,
                    asset,
                    calculated_at=calculated_at or datetime.now(UTC),
                )
                run = session.get(IngestionRun, run_id)
                if run is None:
                    raise RuntimeError(f"ingestion run {run_id} disappeared")
                run.status = "success"
                run.finished_at = datetime.now(UTC)
                run.duration_ms = _elapsed_ms(clock_started)
                run.candles_upserted = len(candles)
                result = IngestionResult(
                    run_id=run_id,
                    symbol=normalized_symbol,
                    candles_processed=len(candles),
                    risk_snapshot_id=snapshot.id if snapshot else None,
                )
            return result
        except Exception as exc:
            self._record_failure(run_id, clock_started, exc)
            raise IngestionError(f"could not ingest {normalized_symbol}: {exc}") from exc

    def record_fetch_failure(
        self,
        symbol: str,
        exc: Exception,
        *,
        started_at: datetime,
    ) -> int:
        """Persist a source failure that happened before a candle batch existed."""
        finished_at = datetime.now(UTC)
        normalized_symbol = symbol.strip().upper()
        with self.session_factory.begin() as session:
            run = IngestionRun(
                status="failed",
                source=f"binance:{normalized_symbol}",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(
                    round((finished_at - started_at).total_seconds() * 1000),
                    0,
                ),
                candles_received=0,
                candles_upserted=0,
                error_message=(f"{normalized_symbol}: {type(exc).__name__}: {exc}")[:1000],
            )
            session.add(run)
            session.flush()
            return run.id

    def _start_run(self, symbol: str, started_at: datetime, received: int) -> int:
        with self.session_factory.begin() as session:
            run = IngestionRun(
                status="running",
                source=f"binance:{symbol}",
                started_at=started_at,
                candles_received=received,
                candles_upserted=0,
            )
            session.add(run)
            session.flush()
            return run.id

    def _record_failure(self, run_id: int, clock_started: float, exc: Exception) -> None:
        with self.session_factory.begin() as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = _elapsed_ms(clock_started)
            run.error_message = f"{type(exc).__name__}: {exc}"[:1000]


def _validate_batch(symbol: str, candles: Sequence[CandleData]) -> None:
    opened_at_values: set[datetime] = set()
    for candle in candles:
        if candle.symbol.strip().upper() != symbol:
            raise ValueError(f"batch for {symbol} contains candle for {candle.symbol}")
        if candle.opened_at.tzinfo is None or candle.closed_at.tzinfo is None:
            raise ValueError("candle timestamps must include a timezone")
        if candle.closed_at <= candle.opened_at:
            raise ValueError("candle closing time must be later than opening time")
        if candle.opened_at in opened_at_values:
            raise ValueError(f"duplicate candle in batch at {candle.opened_at.isoformat()}")
        opened_at_values.add(candle.opened_at)
        prices = (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
        )
        if min(prices) <= 0:
            raise ValueError("candle prices must be positive")
        if candle.high_price < max(candle.open_price, candle.low_price, candle.close_price):
            raise ValueError("candle high price is inconsistent")
        if candle.low_price > min(candle.open_price, candle.high_price, candle.close_price):
            raise ValueError("candle low price is inconsistent")
        if candle.volume < 0 or candle.trade_count < 0:
            raise ValueError("candle volume and trade count cannot be negative")


def _upsert_candles(session: Session, asset_id: int, candles: Sequence[CandleData]) -> None:
    for start in range(0, len(candles), _UPSERT_BATCH_SIZE):
        batch = candles[start : start + _UPSERT_BATCH_SIZE]
        values = [
            {
                "asset_id": asset_id,
                "opened_at": candle.opened_at,
                "closed_at": candle.closed_at,
                "open_price": candle.open_price,
                "high_price": candle.high_price,
                "low_price": candle.low_price,
                "close_price": candle.close_price,
                "volume": candle.volume,
                "trade_count": candle.trade_count,
            }
            for candle in batch
        ]
        statement = insert(Candle).values(values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Candle.asset_id, Candle.opened_at],
                set_={
                    "closed_at": statement.excluded.closed_at,
                    "open_price": statement.excluded.open_price,
                    "high_price": statement.excluded.high_price,
                    "low_price": statement.excluded.low_price,
                    "close_price": statement.excluded.close_price,
                    "volume": statement.excluded.volume,
                    "trade_count": statement.excluded.trade_count,
                },
            )
        )


def _elapsed_ms(started_at: float) -> int:
    return max(round((perf_counter() - started_at) * 1000), 0)
