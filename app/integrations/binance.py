from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import sleep as default_sleep
from typing import Any

import httpx

INTERVAL_MILLISECONDS = {"15m": 15 * 60 * 1000}


class BinanceClientError(RuntimeError):
    """Raised when public market data cannot be retrieved or parsed safely."""


class BinanceRateLimitError(BinanceClientError):
    """Raised when Binance keeps rejecting requests due to its rate limit."""


@dataclass(frozen=True, slots=True)
class CandleData:
    symbol: str
    opened_at: datetime
    closed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    trade_count: int


def parse_kline(symbol: str, payload: list[Any]) -> CandleData:
    try:
        if len(payload) < 9:
            raise ValueError("too few fields")
        opened_at_ms = int(payload[0])
        closed_at_ms = int(payload[6])
        open_price = Decimal(str(payload[1]))
        high_price = Decimal(str(payload[2]))
        low_price = Decimal(str(payload[3]))
        close_price = Decimal(str(payload[4]))
        volume = Decimal(str(payload[5]))
        trade_count = int(payload[8])
        if min(open_price, high_price, low_price, close_price) <= 0:
            raise ValueError("prices must be positive")
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
            raise ValueError("high and low must contain open and close")
        if volume < 0 or trade_count < 0 or closed_at_ms <= opened_at_ms:
            raise ValueError("invalid volume, trades, or timestamps")
    except (IndexError, TypeError, ValueError, InvalidOperation) as exc:
        raise BinanceClientError(f"invalid kline payload for {symbol}") from exc

    return CandleData(
        symbol=symbol.strip().upper(),
        opened_at=datetime.fromtimestamp(opened_at_ms / 1000, tz=UTC),
        closed_at=datetime.fromtimestamp(closed_at_ms / 1000, tz=UTC),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
        trade_count=trade_count,
    )


class BinanceClient:
    def __init__(
        self,
        *,
        base_url: str = "https://data-api.binance.vision",
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        page_limit: int = 1000,
        sleep: Callable[[float], None] = default_sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if not 1 <= page_limit <= 1000:
            raise ValueError("page_limit must be between 1 and 1000")
        self.max_attempts = max_attempts
        self.page_limit = page_limit
        self.sleep = sleep
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": "crypto-risk-monitor/0.1"},
        )

    def fetch_candles(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str = "15m",
    ) -> list[CandleData]:
        if interval not in INTERVAL_MILLISECONDS:
            raise ValueError(f"unsupported candle interval: {interval}")
        _require_aware_datetime(start, "start")
        _require_aware_datetime(end, "end")
        if start >= end:
            raise ValueError("start must be earlier than end")

        normalized_symbol = symbol.strip().upper()
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        interval_ms = INTERVAL_MILLISECONDS[interval]
        candles: dict[datetime, CandleData] = {}

        while start_ms < end_ms:
            payload = self._get_klines(
                {
                    "symbol": normalized_symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms - 1,
                    "limit": self.page_limit,
                }
            )
            if not payload:
                break
            page = [parse_kline(normalized_symbol, raw) for raw in payload]
            for candle in page:
                if candle.opened_at < end:
                    candles[candle.opened_at] = candle
            if len(payload) < self.page_limit:
                break
            next_start = int(page[-1].opened_at.timestamp() * 1000) + interval_ms
            if next_start <= start_ms:
                raise BinanceClientError("Binance pagination did not advance")
            start_ms = next_start

        return [candles[key] for key in sorted(candles)]

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_klines(self, params: dict[str, str | int]) -> list[list[Any]]:
        for attempt in range(self.max_attempts):
            try:
                response = self.http.get("/api/v3/klines", params=params)
            except httpx.TimeoutException as exc:
                if attempt == self.max_attempts - 1:
                    raise BinanceClientError("Binance request timed out after retries") from exc
                self.sleep(_backoff_seconds(attempt))
                continue
            except httpx.HTTPError as exc:
                raise BinanceClientError("Binance request failed") from exc

            if response.status_code == 429:
                if attempt == self.max_attempts - 1:
                    raise BinanceRateLimitError("Binance rate limit persisted after retries")
                self.sleep(_retry_after(response, attempt))
                continue
            if response.status_code >= 500:
                if attempt == self.max_attempts - 1:
                    raise BinanceClientError(
                        f"Binance returned HTTP {response.status_code} after retries"
                    )
                self.sleep(_backoff_seconds(attempt))
                continue
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise BinanceClientError("Binance returned an invalid response") from exc
            if not isinstance(payload, list) or any(not isinstance(row, list) for row in payload):
                raise BinanceClientError("Binance returned an unexpected response shape")
            return payload

        raise BinanceClientError("Binance request exhausted all attempts")


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")


def _backoff_seconds(attempt: int) -> float:
    return 0.5 * (2**attempt)


def _retry_after(response: httpx.Response, attempt: int) -> float:
    try:
        return max(float(response.headers.get("Retry-After", "")), 0.0)
    except ValueError:
        return _backoff_seconds(attempt)
