from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PositionUpsert(BaseModel):
    quantity: Decimal = Field(gt=0)
    cost_basis_brl: Decimal | None = Field(default=None, gt=0)


class RuleUpdate(BaseModel):
    threshold: Decimal | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "RuleUpdate":
        if self.threshold is None and self.enabled is None:
            raise ValueError("threshold or enabled must be provided")
        return self


class AlertTransitionRequest(BaseModel):
    status: Literal["acknowledged", "resolved", "dismissed"]

