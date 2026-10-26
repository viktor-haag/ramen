from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.enums import CoverLetterFormat, CoverLetterLanguage, CoverLetterStatus, MessageRole


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    builtin: bool
    created_at: datetime


class TemplatePatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ContextIn(BaseModel):
    profile: bool = True
    document_ids: list[int] = Field(default_factory=list)
    notes: Annotated[str, StringConstraints(max_length=5000)] = ""


class CoverLetterIn(BaseModel):
    format: CoverLetterFormat
    template_id: int | None = None
    language: CoverLetterLanguage
    context: ContextIn

    @model_validator(mode="after")
    def _latex_needs_template(self) -> "CoverLetterIn":
        if self.format == CoverLetterFormat.latex and self.template_id is None:
            raise ValueError("template_id is required for latex cover letters")
        return self


class MessageIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ContentIn(BaseModel):
    content: Annotated[str, StringConstraints(max_length=200_000)]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: MessageRole
    text: str
    created_at: datetime


class CoverLetterOut(BaseModel):
    id: int
    application_id: int
    format: CoverLetterFormat
    template_id: int | None
    template_name: str | None
    language: CoverLetterLanguage
    context: dict
    content: str
    status: CoverLetterStatus
    error: dict | None
    compile_log: str | None
    pdf_available: bool  # `pdf_path` set and the file exists
    compiler_available: bool
    compiled_at: datetime | None
    updated_at: datetime
    messages: list[MessageOut]
