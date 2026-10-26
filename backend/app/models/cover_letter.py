from datetime import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.application import Application
from app.models.enums import CoverLetterFormat, CoverLetterLanguage, CoverLetterStatus, MessageRole
from app.models.posting import utcnow


def _default_context() -> dict:
    return {"profile": True, "document_ids": [], "notes": ""}


class CoverLetterTemplate(Base):
    __tablename__ = "cover_letter_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    content: Mapped[str]
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CoverLetter(Base):
    """The cover letter draft of an application (at most one per application)."""

    __tablename__ = "cover_letter"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), unique=True
    )
    format: Mapped[CoverLetterFormat] = mapped_column(str_enum(CoverLetterFormat, "cover_letter_format"))
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("cover_letter_template.id", ondelete="SET NULL")
    )
    # Copy of the template TeX at creation time (survives template deletion or edits).
    template_content: Mapped[str | None]
    language: Mapped[CoverLetterLanguage] = mapped_column(
        str_enum(CoverLetterLanguage, "cover_letter_language")
    )
    context: Mapped[dict] = mapped_column(JSON, default=_default_context)
    content: Mapped[str]
    status: Mapped[CoverLetterStatus] = mapped_column(
        str_enum(CoverLetterStatus, "cover_letter_status"), default=CoverLetterStatus.idle
    )
    error: Mapped[dict | None] = mapped_column(JSON)
    compile_log: Mapped[str | None]
    pdf_path: Mapped[str | None]
    compiled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    application: Mapped[Application] = relationship()
    messages: Mapped[list["CoverLetterMessage"]] = relationship(
        back_populates="cover_letter",
        cascade="all, delete-orphan",
        order_by="CoverLetterMessage.id",
    )


class CoverLetterMessage(Base):
    """Visible chat history only; never sent to the LLM."""

    __tablename__ = "cover_letter_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    cover_letter_id: Mapped[int] = mapped_column(ForeignKey("cover_letter.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "cover_letter_message_role"))
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    cover_letter: Mapped[CoverLetter] = relationship(back_populates="messages")
