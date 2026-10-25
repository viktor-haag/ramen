from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AppStatus
from app.models.posting import utcnow
from app.schemas.application import (
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationPatch,
    StatusChangeIn,
)
from app.services import applications as svc
from app.services import export
from app.services.usage import BERLIN

router = APIRouter()


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    status: Annotated[list[AppStatus] | None, Query()] = None,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> list[ApplicationOut]:
    return svc.applications_out(session, svc.list_applications(session, status, q))


@router.get("/applications/export")
def export_applications(
    format: Literal["csv", "xlsx"],
    status: Annotated[list[AppStatus] | None, Query()] = None,
    q: str | None = None,
    lang: Literal["de", "en"] = "de",
    session: Session = Depends(get_session),
) -> Response:
    now = utcnow()
    rows = export.export_rows(session, status, q, now, lang)
    if format == "csv":
        content, media_type = export.to_csv(rows, lang), "text/csv; charset=utf-8"
    else:
        content = export.to_xlsx(rows, lang)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    stem = "ramen-bewerbungen" if lang == "de" else "ramen-applications"
    filename = f"{stem}-{now.astimezone(BERLIN).date().isoformat()}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/applications/{app_id}", response_model=ApplicationDetailOut)
def get_application(app_id: int, session: Session = Depends(get_session)) -> ApplicationDetailOut:
    return svc.application_detail(session, svc.get_application(session, app_id))


@router.patch("/applications/{app_id}", response_model=ApplicationDetailOut)
def patch_application(
    app_id: int, patch: ApplicationPatch, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.update_application(session, app_id, patch, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)


@router.post("/applications/{app_id}/status", response_model=ApplicationDetailOut)
def change_status(
    app_id: int, body: StatusChangeIn, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.change_status(session, app_id, body.to, body.comment, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)


@router.post("/applications/{app_id}/reopen", response_model=ApplicationDetailOut)
def reopen(
    app_id: int, body: StatusChangeIn, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.reopen(session, app_id, body.to, body.comment, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)
