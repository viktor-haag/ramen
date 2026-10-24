from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.schemas.me import (
    DocumentOut, DocumentPatch, ExtractOut, FreeTextIn, GenerateOut, MarkdownIn, ProfileOut,
)
from app.services import profile_docs as docs
from app.services import user_profile

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/me/documents", response_model=list[DocumentOut])
def list_documents(session: Session = Depends(get_session)):
    return docs.list_documents(session)


@router.post("/me/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    file: Annotated[UploadFile, File()],
    description: Annotated[str | None, Form()] = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    doc = docs.upload(session, settings, file, description)
    try:
        session.commit()
    except BaseException:
        docs.discard_file(settings, doc)
        raise
    return doc


@router.patch("/me/documents/{doc_id}", response_model=DocumentOut)
def patch_document(doc_id: int, patch: DocumentPatch, session: Session = Depends(get_session)):
    fields = {name: getattr(patch, name) for name in patch.model_fields_set}
    doc = docs.update(session, doc_id, **fields)
    session.commit()
    return doc


@router.delete("/me/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> Response:
    docs.delete(session, settings, doc_id)
    session.commit()
    return Response(status_code=204)


@router.get("/me/documents/{doc_id}/download")
def download_document(
    doc_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> FileResponse:
    doc, path = docs.file_path(session, settings, doc_id)
    return FileResponse(path, filename=doc.display_name, media_type=doc.mime)


@router.post("/me/documents/{doc_id}/extract", response_model=ExtractOut)
def extract_document(doc_id: int, request: Request) -> ExtractOut:
    doc, exceeded = docs.extract_with_llm(request.app.state.session_factory, request.app.state.settings, doc_id)
    return ExtractOut(document=DocumentOut.model_validate(doc), limit_exceeded=exceeded)


@router.get("/me/profile", response_model=ProfileOut)
def get_profile(session: Session = Depends(get_session)):
    return user_profile.get(session)


@router.put("/me/profile/free-text", response_model=ProfileOut)
def put_free_text(body: FreeTextIn, session: Session = Depends(get_session)):
    out = user_profile.update_free_text(session, body.free_text)
    session.commit()
    return out


@router.put("/me/profile/markdown", response_model=ProfileOut)
def put_markdown(body: MarkdownIn, session: Session = Depends(get_session)):
    out = user_profile.update_markdown(session, body.profile_markdown)
    session.commit()
    return out


@router.post("/me/profile/generate", response_model=GenerateOut)
def generate_profile(request: Request, overwrite: bool = False) -> GenerateOut:
    profile, exceeded = user_profile.generate(request.app.state.session_factory, overwrite=overwrite)
    return GenerateOut(profile=profile, limit_exceeded=exceeded)
