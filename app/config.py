from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
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
    risk_profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    operator_password: str = "change_me"
    session_secret: str = "replace_with_a_long_random_value"
    session_cookie_secure: bool = False
    discord_webhook_url: HttpUrl | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        values = tuple(
            symbol.strip().upper()
            for symbol in self.symbols_csv.split(",")
            if symbol.strip()
        )
        if not values:
            raise ValueError("SYMBOLS must contain at least one market symbol")
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
