import pytest

from app.domain.metrics import calculate_market_metrics


def test_market_metrics_from_15_minute_candles():
    closes = [100.0] * 96 + [101.0, 102.0, 103.0, 104.0]
    volumes = [10.0] * 99 + [30.0]

    result = calculate_market_metrics(closes, volumes)

    assert result.last_price == pytest.approx(104.0)
    assert result.return_1h_pct == pytest.approx(4.0)
    assert result.return_24h_pct == pytest.approx(4.0)
    assert result.volatility_24h_pct is not None
    assert result.volatility_24h_pct > 0
    assert result.volume_ratio == pytest.approx(3.0)


def test_constant_market_has_zero_return_volatility_and_drawdown():
    closes = [100.0] * 672
    volumes = [10.0] * 672

    result = calculate_market_metrics(closes, volumes)

    assert result.return_1h_pct == pytest.approx(0.0)
    assert result.return_24h_pct == pytest.approx(0.0)
    assert result.volatility_24h_pct == pytest.approx(0.0)
    assert result.drawdown_7d_pct == pytest.approx(0.0)
    assert result.volume_ratio == pytest.approx(1.0)


def test_drawdown_is_measured_from_the_highest_price_in_seven_days():
    closes = [100.0] * 670 + [80.0, 90.0]
    volumes = [10.0] * 672

    result = calculate_market_metrics(closes, volumes)

    assert result.drawdown_7d_pct == pytest.approx(-10.0)


def test_insufficient_history_is_reported_without_inventing_metrics():
    result = calculate_market_metrics([100.0, 101.0, 102.0, 103.0], [10.0] * 4)

    assert result.last_price == pytest.approx(103.0)
    assert result.return_1h_pct is None
    assert result.return_24h_pct is None
    assert result.volatility_24h_pct is None
    assert result.drawdown_7d_pct is None
    assert result.volume_ratio is None


@pytest.mark.parametrize(
    ("closes", "volumes"),
    [
        ([], []),
        ([100.0], []),
        ([0.0], [10.0]),
        ([100.0], [-1.0]),
    ],
)
def test_invalid_market_series_are_rejected(closes, volumes):
    with pytest.raises(ValueError):
        calculate_market_metrics(closes, volumes)
