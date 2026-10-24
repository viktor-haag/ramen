from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Appointment, Contact
from app.schemas.application import AppointmentIn, AppointmentPatch, ContactIn, ContactPatch
from app.services.applications import get_application


def _appointment(session: Session, appointment_id: int) -> Appointment:
    obj = session.get(Appointment, appointment_id)
    if obj is None:
        raise NotFoundError(
            "appointment_not_found", "Appointment not found", {"appointment_id": appointment_id}
        )
    return obj


def _contact(session: Session, contact_id: int) -> Contact:
    obj = session.get(Contact, contact_id)
    if obj is None:
        raise NotFoundError("contact_not_found", "Contact not found", {"contact_id": contact_id})
    return obj


def list_appointments(session: Session, app_id: int) -> list[Appointment]:
    get_application(session, app_id)
    return list(
        session.scalars(
            select(Appointment)
            .where(Appointment.application_id == app_id)
            .order_by(Appointment.starts_at, Appointment.id)
        )
    )


def create_appointment(session: Session, app_id: int, data: AppointmentIn) -> Appointment:
    get_application(session, app_id)
    obj = Appointment(application_id=app_id, **data.model_dump())
    session.add(obj)
    session.flush()
    return obj


def update_appointment(session: Session, appointment_id: int, patch: AppointmentPatch) -> Appointment:
    obj = _appointment(session, appointment_id)
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    session.flush()
    return obj


def delete_appointment(session: Session, appointment_id: int) -> None:
    session.delete(_appointment(session, appointment_id))
    session.flush()


def list_contacts(session: Session, app_id: int) -> list[Contact]:
    get_application(session, app_id)
    return list(
        session.scalars(select(Contact).where(Contact.application_id == app_id).order_by(Contact.id))
    )


def create_contact(session: Session, app_id: int, data: ContactIn) -> Contact:
    get_application(session, app_id)
    obj = Contact(application_id=app_id, **data.model_dump())
    session.add(obj)
    session.flush()
    return obj


def update_contact(session: Session, contact_id: int, patch: ContactPatch) -> Contact:
    obj = _contact(session, contact_id)
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(obj, name, value)
    session.flush()
    return obj


def delete_contact(session: Session, contact_id: int) -> None:
    session.delete(_contact(session, contact_id))
    session.flush()
