from dataclasses import dataclass
from datetime import datetime

import httpx


@dataclass(frozen=True, slots=True)
class AlertNotification:
    code: str
    label: str
    severity: str
    symbol: str | None
    message: str
    observed_at: datetime


class DiscordNotificationError(RuntimeError):
    """Report a webhook failure without retaining the secret URL."""


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str | None,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.webhook_url = webhook_url.strip() if webhook_url else None
        self.http = httpx.Client(timeout=timeout_seconds, transport=transport)

    def notify(self, notification: AlertNotification) -> bool:
        if not self.webhook_url:
            return False
        try:
            response = self.http.post(
                self.webhook_url,
                json={
                    "username": "Crypto Risk Monitor",
                    "embeds": [
                        {
                            "title": notification.label,
                            "description": (
                                f"**{_display_symbol(notification.symbol)}**\n"
                                f"{notification.message}"
                            ),
                            "color": _severity_color(notification.severity),
                            "footer": {"text": f"Regra: {notification.code}"},
                            "timestamp": notification.observed_at.isoformat(),
                        }
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise DiscordNotificationError("Discord webhook request failed") from None
        return True

    def close(self) -> None:
        self.http.close()


def _display_symbol(symbol: str | None) -> str:
    if not symbol:
        return "Portfólio"
    if symbol.endswith("BRL"):
        return f"{symbol[:-3]}/BRL"
    return symbol


def _severity_color(severity: str) -> int:
    return {"warning": 0xF2B84B, "high": 0xF06A4A, "critical": 0xD9364A}.get(severity, 0x5C9EAD)
