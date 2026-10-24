from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.enums import AppointmentKind, AppStatus, AttachmentKind
from app.models.posting import Posting, utcnow


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_posting.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[AppStatus] = mapped_column(
        str_enum(AppStatus, "app_status"), default=AppStatus.saved
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    salary_expectation: Mapped[str | None]
    channel: Mapped[str | None]
    notes: Mapped[str | None]

    posting: Mapped[Posting] = relationship()
    status_changes: Mapped[list["StatusChange"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="StatusChange.id"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="Appointment.starts_at"
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="Contact.id"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="Attachment.id"
    )


class StatusChange(Base):
    __tablename__ = "status_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    from_status: Mapped[AppStatus | None] = mapped_column(str_enum(AppStatus, "from_status"))
    to_status: Mapped[AppStatus] = mapped_column(str_enum(AppStatus, "to_status"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    comment: Mapped[str | None]

    application: Mapped[Application] = relationship(back_populates="status_changes")


class Appointment(Base):
    __tablename__ = "appointment"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    kind: Mapped[AppointmentKind] = mapped_column(
        str_enum(AppointmentKind, "appointment_kind"), default=AppointmentKind.other
    )
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    note: Mapped[str | None]

    application: Mapped[Application] = relationship(back_populates="appointments")


class Contact(Base):
    __tablename__ = "contact"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    name: Mapped[str]
    role: Mapped[str | None]
    email: Mapped[str | None]
    phone: Mapped[str | None]

    application: Mapped[Application] = relationship(back_populates="contacts")


class Attachment(Base):
    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    filename: Mapped[str]
    display_name: Mapped[str]
    stored_path: Mapped[str]
    kind: Mapped[AttachmentKind] = mapped_column(
        str_enum(AttachmentKind, "attachment_kind"), default=AttachmentKind.other
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    application: Mapped[Application] = relationship(back_populates="attachments")
