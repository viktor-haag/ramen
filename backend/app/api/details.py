from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.models import AttachmentKind
from app.schemas.application import (
    AppointmentIn,
    AppointmentOut,
    AppointmentPatch,
    AttachmentOut,
    ContactIn,
    ContactOut,
    ContactPatch,
)
from app.services import attachments as att_svc
from app.services import details as svc

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/applications/{app_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(app_id: int, session: Session = Depends(get_session)):
    return svc.list_appointments(session, app_id)


@router.post("/applications/{app_id}/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(app_id: int, body: AppointmentIn, session: Session = Depends(get_session)):
    obj = svc.create_appointment(session, app_id, body)
    session.commit()
    return obj


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def patch_appointment(
    appointment_id: int, body: AppointmentPatch, session: Session = Depends(get_session)
):
    obj = svc.update_appointment(session, appointment_id, body)
    session.commit()
    return obj


@router.delete("/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: int, session: Session = Depends(get_session)) -> Response:
    svc.delete_appointment(session, appointment_id)
    session.commit()
    return Response(status_code=204)


@router.get("/applications/{app_id}/contacts", response_model=list[ContactOut])
def list_contacts(app_id: int, session: Session = Depends(get_session)):
    return svc.list_contacts(session, app_id)


@router.post("/applications/{app_id}/contacts", response_model=ContactOut, status_code=201)
def create_contact(app_id: int, body: ContactIn, session: Session = Depends(get_session)):
    obj = svc.create_contact(session, app_id, body)
    session.commit()
    return obj


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def patch_contact(contact_id: int, body: ContactPatch, session: Session = Depends(get_session)):
    obj = svc.update_contact(session, contact_id, body)
    session.commit()
    return obj


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, session: Session = Depends(get_session)) -> Response:
    svc.delete_contact(session, contact_id)
    session.commit()
    return Response(status_code=204)


@router.post("/applications/{app_id}/attachments", response_model=AttachmentOut, status_code=201)
def upload_attachment(
    app_id: int,
    file: Annotated[UploadFile, File()],
    kind: Annotated[AttachmentKind, Form()] = AttachmentKind.other,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    att = att_svc.store(session, settings, app_id, file, kind)
    try:
        session.commit()
    except BaseException:
        att_svc.resolve_path(settings, att.stored_path).unlink(missing_ok=True)
        raise
    return att


@router.get("/attachments/{att_id}/download")
def download_attachment(
    att_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    att, path = att_svc.file_path(session, settings, att_id)
    return FileResponse(path, filename=att.display_name)


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(
    att_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    att_svc.delete(session, settings, att_id)
    session.commit()
    return Response(status_code=204)
