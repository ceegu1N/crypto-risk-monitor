from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str
    symbols_csv: str = Field(
        default="BTCBRL,ETHBRL,SOLBRL,USDTBRL",
        validation_alias="SYMBOLS",
    )
    binance_base_url: HttpUrl = HttpUrl("https://data-api.binance.vision")
    candle_interval: Literal["15m"] = "15m"
    bootstrap_days: PositiveInt = 7
    collector_interval_seconds: PositiveInt = 900
    risk_profile: Literal["conservative", "moderate", "aggressive", "custom"] = "moderate"
    operator_password: str = "change_me"
    session_secret: str = "replace_with_a_long_random_value"
    session_cookie_secure: bool = False
    discord_webhook_url: HttpUrl | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        values = tuple(
            symbol.strip().upper() for symbol in self.symbols_csv.split(",") if symbol.strip()
        )
        if not values:
            raise ValueError("SYMBOLS must contain at least one market symbol")
        return values

    def validate_web_security(self) -> None:
        """Reject development credentials when cookies are configured for HTTPS."""
        if not self.session_cookie_secure:
            return
        default_password = type(self).model_fields["operator_password"].default
        if self.operator_password == default_password or len(self.operator_password) < 12:
            raise ValueError("OPERATOR_PASSWORD must be changed and contain at least 12 characters")
        insecure_secrets = {
            "replace_with_a_long_random_value",
            "local-development-secret-change-me",
        }
        if self.session_secret in insecure_secrets or len(self.session_secret) < 32:
            raise ValueError("SESSION_SECRET must be changed and contain at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
