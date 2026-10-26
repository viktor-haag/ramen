from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    builtin: bool
    created_at: datetime


class TemplatePatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
