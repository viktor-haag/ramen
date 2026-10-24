from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models import DocumentKind, TextSource


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    display_name: str
    mime: str
    kind: DocumentKind
    description: str | None
    text: str | None
    text_source: TextSource | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def usable(self) -> bool:
        """Has text the profile generation can use."""
        return bool(self.text)


class DocumentPatch(BaseModel):
    description: str | None = None
    text: str | None = None  # a given text becomes the manual text; empty or null clears it


class ExtractOut(BaseModel):
    document: DocumentOut
    limit_exceeded: bool


class ProfileOut(BaseModel):
    free_text: str | None
    profile_markdown: str | None
    generated_at: datetime | None
    edited_since_generation: bool
    inputs_changed_since_generation: bool
    version: int
    documents_used: int
    documents_unused: int


class FreeTextIn(BaseModel):
    free_text: str | None = Field(default=None, max_length=20_000)


class MarkdownIn(BaseModel):
    profile_markdown: str = ""


class GenerateOut(BaseModel):
    profile: ProfileOut
    limit_exceeded: bool
