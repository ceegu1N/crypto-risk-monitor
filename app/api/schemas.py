from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PositionUpsert(BaseModel):
    quantity: Decimal = Field(
        gt=0,
        max_digits=36,
        decimal_places=12,
        allow_inf_nan=False,
    )
    cost_basis_brl: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=30,
        decimal_places=12,
        allow_inf_nan=False,
    )


class RuleUpdate(BaseModel):
    threshold: Decimal | None = Field(
        default=None,
        max_digits=20,
        decimal_places=8,
        allow_inf_nan=False,
    )
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "RuleUpdate":
        if self.threshold is None and self.enabled is None:
            raise ValueError("threshold or enabled must be provided")
        return self


class AlertTransitionRequest(BaseModel):
    status: Literal["acknowledged", "resolved", "dismissed"]


class RiskProfileUpdate(BaseModel):
    profile: Literal["conservative", "moderate", "aggressive", "custom"]
