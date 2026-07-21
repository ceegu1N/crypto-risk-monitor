from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.integrations.binance import (
    BinanceClient,
    BinanceClientError,
    BinanceRateLimitError,
    parse_kline,
)


def sample_kline(opened_at_ms: int = 1_700_000_000_000) -> list[object]:
    return [
        opened_at_ms,
        "100.10",
        "105.20",
        "99.50",
        "103.40",
        "12.345",
        opened_at_ms + 899_999,
        "1270.00",
        42,
        "6.0",
        "617.0",
        "0",
    ]


def test_parse_kline_uses_utc_and_decimal_values():
    candle = parse_kline("BTCBRL", sample_kline())

    assert candle.symbol == "BTCBRL"
    assert candle.opened_at.tzinfo is UTC
    assert candle.open_price == Decimal("100.10")
    assert candle.high_price == Decimal("105.20")
    assert candle.low_price == Decimal("99.50")
    assert candle.close_price == Decimal("103.40")
    assert candle.volume == Decimal("12.345")
    assert candle.trade_count == 42


def test_invalid_kline_payload_is_rejected():
    with pytest.raises(BinanceClientError, match="invalid kline"):
        parse_kline("BTCBRL", [1, "100"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__(2, "99.00"),
        lambda payload: payload.__setitem__(3, "104.00"),
        lambda payload: payload.__setitem__(6, payload[0]),
    ],
)
def test_parse_kline_rejects_invalid_price_envelopes_and_time_windows(mutate):
    payload = sample_kline()
    mutate(payload)

    with pytest.raises(BinanceClientError, match="invalid kline"):
        parse_kline("BTCBRL", payload)


def test_timeout_is_retried_before_a_clear_error():
    attempts = 0
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow upstream", request=request)

    client = BinanceClient(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        sleep=waits.append,
    )

    with pytest.raises(BinanceClientError, match="timed out"):
        client.fetch_candles(
            "BTCBRL",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )

    assert attempts == 2
    assert waits == [0.5]


def test_rate_limit_has_a_specific_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"}, request=request)

    client = BinanceClient(
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        sleep=lambda _: None,
    )

    with pytest.raises(BinanceRateLimitError, match="rate limit"):
        client.fetch_candles(
            "BTCBRL",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_fetch_candles_paginates_without_repeating_the_last_candle():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    interval = timedelta(minutes=15)
    opened = [int((start + index * interval).timestamp() * 1000) for index in range(3)]
    requested_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_start = int(request.url.params["startTime"])
        requested_starts.append(requested_start)
        available = [value for value in opened if value >= requested_start]
        payload = [sample_kline(value) for value in available[:2]]
        return httpx.Response(200, json=payload, request=request)

    client = BinanceClient(
        transport=httpx.MockTransport(handler),
        page_limit=2,
        sleep=lambda _: None,
    )

    candles = client.fetch_candles("BTCBRL", start=start, end=start + 3 * interval)

    assert [candle.opened_at for candle in candles] == [
        start,
        start + interval,
        start + 2 * interval,
    ]
    assert requested_starts == [opened[0], opened[2]]


def test_non_list_response_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True}, request=request)

    client = BinanceClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)

    with pytest.raises(BinanceClientError, match="unexpected response"):
        client.fetch_candles(
            "BTCBRL",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_fetch_price_reads_a_fresh_spot_quote():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/ticker/price"
        assert request.url.params["symbol"] == "BTCBRL"
        return httpx.Response(200, json={"symbol": "BTCBRL", "price": "345678.90"}, request=request)

    client = BinanceClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)

    assert client.fetch_price("BTCBRL") == Decimal("345678.90")
