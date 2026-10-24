from pydantic import BaseModel, Field


class PluginOut(BaseModel):
    name: str
    display_name: str
    capabilities: list[str]
    url_patterns: list[str]
    enabled: bool
    settings: dict
    settings_schema: dict | None
    error: str | None


class PluginUpdate(BaseModel):
    enabled: bool
    settings: dict = Field(default_factory=dict)
