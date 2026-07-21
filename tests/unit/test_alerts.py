import traceback
from datetime import UTC, datetime

import httpx
import pytest

from app.integrations.discord import AlertNotification, DiscordNotifier
from app.services.alerts import (
    InvalidAlertTransition,
    ensure_operator_transition,
    observed_value_worsened,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("new", "acknowledged"),
        ("new", "resolved"),
        ("new", "dismissed"),
        ("acknowledged", "resolved"),
        ("acknowledged", "dismissed"),
    ],
)
def test_valid_operator_transitions(current, target):
    ensure_operator_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [("resolved", "acknowledged"), ("dismissed", "resolved"), ("new", "new")],
)
def test_invalid_operator_transitions_are_rejected(current, target):
    with pytest.raises(InvalidAlertTransition):
        ensure_operator_transition(current, target)


def test_worsening_value_respects_the_rule_direction():
    assert observed_value_worsened("gte", previous=4.0, current=5.0)
    assert observed_value_worsened("lte", previous=-5.0, current=-7.0)
    assert not observed_value_worsened("gte", previous=5.0, current=4.0)


def test_discord_without_webhook_is_a_noop():
    notifier = DiscordNotifier(None)

    assert notifier.notify(_notification()) is False


def test_discord_posts_a_compact_alert_message():
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(__import__("json").loads(request.content))
        return httpx.Response(204, request=request)

    notifier = DiscordNotifier(
        "https://discord.example/webhook",
        transport=httpx.MockTransport(handler),
    )

    assert notifier.notify(_notification()) is True
    assert received[0]["username"] == "Crypto Risk Monitor"
    assert "BTC/BRL" in received[0]["embeds"][0]["description"]


def test_discord_failure_does_not_expose_the_webhook_secret():
    webhook = "https://discord.example/api/webhooks/123/super-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    notifier = DiscordNotifier(webhook, transport=httpx.MockTransport(handler))

    try:
        notifier.notify(_notification())
    except Exception:  # noqa: BLE001 - the traceback is the behavior under test
        rendered = traceback.format_exc()
    else:
        pytest.fail("a failed Discord request must raise an exception")

    assert "super-secret-token" not in rendered
    assert webhook not in rendered
    assert "Discord webhook request failed" in rendered


def _notification() -> AlertNotification:
    return AlertNotification(
        code="volatility_24h",
        label="Volatilidade em 24 horas",
        severity="warning",
        symbol="BTCBRL",
        message="Valor observado 4,50%; limite 4,00%.",
        observed_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
    )
