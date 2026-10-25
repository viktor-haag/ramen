from datetime import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.enums import LLMProvider, LLMPurposeKind, ThinkingLevel
from app.models.posting import utcnow


class LLMConfig(Base):
    __tablename__ = "llm_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    provider: Mapped[LLMProvider] = mapped_column(str_enum(LLMProvider, "llm_provider"))
    base_url: Mapped[str | None]
    api_key: Mapped[str | None]
    model: Mapped[str]
    thinking: Mapped[ThinkingLevel] = mapped_column(
        str_enum(ThinkingLevel, "thinking_level"), default=ThinkingLevel.off
    )
    supports_images: Mapped[bool] = mapped_column(default=False)
    extra_body: Mapped[dict] = mapped_column(JSON, default=dict)
    extra_headers: Mapped[dict] = mapped_column(JSON, default=dict)
    price_in: Mapped[float | None]
    price_out: Mapped[float | None]
    daily_limit_kind: Mapped[str] = mapped_column(default="none", server_default="none")  # none | tokens | eur
    daily_limit_value: Mapped[float | None]
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class LLMPurpose(Base):
    __tablename__ = "llm_purpose"

    purpose: Mapped[LLMPurposeKind] = mapped_column(
        str_enum(LLMPurposeKind, "llm_purpose_kind"), primary_key=True
    )
    config_id: Mapped[int | None] = mapped_column(ForeignKey("llm_config.id", ondelete="SET NULL"))


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    config_id: Mapped[int | None] = mapped_column(ForeignKey("llm_config.id", ondelete="SET NULL"))
    purpose: Mapped[str]
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated: Mapped[bool] = mapped_column(default=False)
    ok: Mapped[bool] = mapped_column(default=True)
