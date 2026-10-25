from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class SettingsIn(BaseModel):
    fit_auto: bool
    fit_concurrency: int = Field(ge=1, le=8)
    daily_limit_kind: Literal["none", "tokens", "eur"]
    daily_limit_value: int | float | None = Field(default=None, ge=0, allow_inf_nan=False, validate_default=True)
    fit_language: Literal["en", "de"] = "en"  # language of automatic fit explanations
    update_check: bool = True  # periodically look for a newer release on GitHub

    @field_validator("daily_limit_value", mode="after")
    @classmethod
    def _limit_value(cls, value: int | float | None, info: ValidationInfo) -> int | float | None:
        kind = info.data.get("daily_limit_kind")
        if kind == "none":
            return None
        if kind is None:  # kind itself is invalid; reported on its own field
            return value
        if not value:
            raise ValueError("daily_limit_value must be greater than 0 for this limit kind")
        if kind == "tokens":  # whole tokens
            if value != int(value):
                raise ValueError("daily_limit_value must be a whole number of tokens")
            return int(value)
        return value


class SettingsOut(SettingsIn):
    pass
