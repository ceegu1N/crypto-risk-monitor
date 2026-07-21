import pytest

from app.domain.portfolio import Position, calculate_portfolio


def test_portfolio_concentration_and_pnl():
    positions = [
        Position("BTCBRL", 0.01, 300_000),
        Position("USDTBRL", 100, 5),
    ]
    prices = {"BTCBRL": 330_000, "USDTBRL": 5.1}
    volatilities = {"BTCBRL": 4.0, "USDTBRL": 0.2}

    result = calculate_portfolio(positions, prices, volatilities)

    assert result.total_value_brl == pytest.approx(3_810)
    assert result.cost_basis_value_brl == pytest.approx(3_500)
    assert result.pnl_brl == pytest.approx(310)
    assert result.pnl_pct == pytest.approx(310 / 3_500 * 100)
    assert result.max_weight_pct > 80
    assert result.volatile_asset_share_pct == pytest.approx(3_300 / 3_810 * 100)
    assert result.positions[0].risk_contribution == pytest.approx(
        result.positions[0].weight_pct / 100 * 4.0
    )


def test_position_without_cost_basis_keeps_pnl_unknown():
    result = calculate_portfolio(
        [Position("SOLBRL", 2)],
        {"SOLBRL": 500},
        {"SOLBRL": 5.0},
    )

    assert result.cost_basis_value_brl is None
    assert result.pnl_brl is None
    assert result.pnl_pct is None
    assert result.positions[0].pnl_brl is None


def test_portfolio_24h_return_uses_each_positions_implied_previous_value():
    result = calculate_portfolio(
        [Position("BTCBRL", 1), Position("USDTBRL", 100)],
        {"BTCBRL": 110, "USDTBRL": 1},
        {"BTCBRL": 4.0, "USDTBRL": 0.1},
        returns_24h_pct={"BTCBRL": 10.0, "USDTBRL": 0.0},
    )

    assert result.return_24h_pct == pytest.approx(5.0)


def test_portfolio_24h_return_is_unknown_when_one_position_has_no_return():
    result = calculate_portfolio(
        [Position("BTCBRL", 1), Position("USDTBRL", 100)],
        {"BTCBRL": 110, "USDTBRL": 1},
        {"BTCBRL": 4.0, "USDTBRL": 0.1},
        returns_24h_pct={"BTCBRL": 10.0, "USDTBRL": None},
    )

    assert result.return_24h_pct is None


def test_empty_portfolio_returns_zero_exposure():
    result = calculate_portfolio([], {}, {})

    assert result.total_value_brl == 0
    assert result.max_weight_pct == 0
    assert result.volatile_asset_share_pct == 0
    assert result.positions == ()


def test_missing_market_price_is_rejected():
    with pytest.raises(ValueError, match="missing price for BTCBRL"):
        calculate_portfolio([Position("BTCBRL", 0.01)], {}, {})


@pytest.mark.parametrize(
    "position",
    [
        Position("BTCBRL", 0),
        Position("BTCBRL", -1),
        Position("BTCBRL", 1, 0),
    ],
)
def test_invalid_position_values_are_rejected(position):
    with pytest.raises(ValueError):
        calculate_portfolio([position], {"BTCBRL": 100}, {})


def test_duplicate_symbols_are_rejected():
    with pytest.raises(ValueError, match="duplicate position"):
        calculate_portfolio(
            [Position("BTCBRL", 0.01), Position("BTCBRL", 0.02)],
            {"BTCBRL": 100},
            {},
        )
