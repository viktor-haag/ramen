"""Shared test helper: a cover-letter LLM answer in the plain-text marker format."""
from app.services.stream_filter import NOTE_MARKER


def answer_text(document: str, note: str = "ok") -> str:
    return f"{document}\n{NOTE_MARKER}\n{note}"
