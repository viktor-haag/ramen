from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.enums import DocumentKind, TextSource
from app.models.posting import utcnow


class ProfileDocument(Base):
    __tablename__ = "profile_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str]
    display_name: Mapped[str]
    stored_path: Mapped[str]
    mime: Mapped[str]
    kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind, "document_kind"))
    description: Mapped[str | None]
    text: Mapped[str | None]
    text_source: Mapped[TextSource | None] = mapped_column(str_enum(TextSource, "text_source"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UserProfile(Base):
    """Single row; the service layer always uses id 1."""

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    free_text: Mapped[str | None]
    profile_markdown: Mapped[str | None]
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    edited_since_generation: Mapped[bool] = mapped_column(default=False)
    inputs_changed_since_generation: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
