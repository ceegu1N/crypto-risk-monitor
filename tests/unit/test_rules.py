import pytest

from app.domain.rules import evaluate_market_rules, evaluate_rules, rules_for_profile


def test_moderate_profile_flags_volatility():
    rules = rules_for_profile("moderate")

    events = evaluate_market_rules({"volatility_24h_pct": 4.5}, rules)

    assert [event.code for event in events] == ["volatility_24h"]
    assert events[0].observed == 4.5
    assert events[0].threshold == 4.0
    assert events[0].operator == "gte"
    assert "4,50%" in events[0].message


def test_value_below_a_greater_than_rule_does_not_raise_an_alert():
    rules = rules_for_profile("moderate")

    events = evaluate_market_rules({"volatility_24h_pct": 3.99}, rules)

    assert events == []


def test_drop_rule_uses_less_than_or_equal_comparison():
    rules = rules_for_profile("moderate")

    events = evaluate_market_rules({"return_24h_pct": -5.1}, rules)

    assert [event.code for event in events] == ["price_drop_24h"]
    assert events[0].operator == "lte"


def test_missing_metrics_do_not_create_false_alerts():
    rules = rules_for_profile("moderate")

    events = evaluate_market_rules(
        {"return_24h_pct": None, "volatility_24h_pct": None},
        rules,
    )

    assert events == []


def test_portfolio_rules_are_not_evaluated_as_market_rules():
    rules = rules_for_profile("moderate")

    market_events = evaluate_market_rules({"max_position_weight_pct": 99.0}, rules)
    all_events = evaluate_rules({"max_position_weight_pct": 99.0}, rules, scope="portfolio")

    assert market_events == []
    assert [event.code for event in all_events] == ["portfolio_concentration"]


def test_profiles_get_progressively_more_tolerant():
    conservative = {rule.code: rule.threshold for rule in rules_for_profile("conservative")}
    moderate = {rule.code: rule.threshold for rule in rules_for_profile("moderate")}
    aggressive = {rule.code: rule.threshold for rule in rules_for_profile("aggressive")}

    assert conservative["volatility_24h"] < moderate["volatility_24h"]
    assert moderate["volatility_24h"] < aggressive["volatility_24h"]
    assert conservative["price_drop_24h"] > moderate["price_drop_24h"]
    assert moderate["price_drop_24h"] > aggressive["price_drop_24h"]


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="unknown risk profile"):
        rules_for_profile("reckless")
