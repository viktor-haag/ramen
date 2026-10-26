from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.downloads import content_disposition
from app.db import get_session
from app.schemas.cover_letter import TemplateOut, TemplatePatch
from app.services import cover_letter_templates as templates
from app.services.attachments import safe_filename

router = APIRouter()


@router.get("/cover-letter-templates", response_model=list[TemplateOut])
def list_templates(session: Session = Depends(get_session)):
    return templates.list_templates(session)


@router.post("/cover-letter-templates", response_model=TemplateOut, status_code=201)
def upload_template(file: Annotated[UploadFile, File()], session: Session = Depends(get_session)):
    template = templates.upload(session, file)
    session.commit()
    return template


@router.patch("/cover-letter-templates/{template_id}", response_model=TemplateOut)
def rename_template(template_id: int, patch: TemplatePatch, session: Session = Depends(get_session)):
    template = templates.rename(session, template_id, patch.name)
    session.commit()
    return template


@router.delete("/cover-letter-templates/{template_id}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(get_session)) -> Response:
    templates.delete(session, template_id)
    session.commit()
    return Response(status_code=204)


@router.get("/cover-letter-templates/{template_id}/download")
def download_template(template_id: int, session: Session = Depends(get_session)) -> Response:
    template = templates.get_template(session, template_id)
    filename = safe_filename(template.name) + ".tex"
    return Response(
        content=template.content.encode("utf-8"),
        media_type="text/x-tex; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )
