from pydantic import BaseModel, field_validator

MAX_PROMPT_CHARS = 20_000


class PromptOut(BaseModel):
    purpose: str
    text: str  # the editable part in effect (custom or default)
    default_text: str
    fixed_text: str  # locked format part, raw (may contain `{language_line}`)
    customized: bool


class PromptIn(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text must not be blank")
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"text must be at most {MAX_PROMPT_CHARS} characters")
        return text
