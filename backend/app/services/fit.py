"""Fit evaluation: rate one posting against the user's profile with the `fit` LLM.

The prompt carries the profile markdown (current version) and the posting's key facts plus its description
(cut to DESCRIPTION_CAP). Documents are never sent. The answer is validated; one retry with a correction
message, otherwise `llm_invalid_output`. No DB session is held during the LLM calls.
"""
import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.errors import ConflictError, NotFoundError, UpstreamError
from app.llm.base import Message
from app.llm.factory import ConfigData
from app.llm.runner import llm_call
from app.models import Posting, UserProfile
from app.services import prompts
from app.services.posting_text import posting_block

PURPOSE = "fit"
MAX_TOKENS = 2048
RATINGS = ("good", "moderate", "poor")

FIT_SCHEMA = {
    "type": "object",
    "properties": {
        "rating": {"type": "string", "enum": list(RATINGS)},
        "explanation": {"type": "string"},
    },
    "required": ["rating", "explanation"],
    "additionalProperties": False,
}

CORRECTION = (
    'Your answer was not usable. Answer again with only a JSON object {"rating": "good" | "moderate" | "poor", '
    '"explanation": "<2-4 sentences>"}: the rating must be one of those three values and the explanation '
    "must not be empty."
)


@dataclass(frozen=True)
class FitResult:
    rating: str
    explanation: str
    profile_version: int
    limit_exceeded: bool


def _language(lang: str) -> str:
    return "German" if lang == "de" else "English"


_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def build_messages(profile_md: str, posting: Posting, lang: str, editable: str) -> tuple[str, list[Message]]:
    system = prompts.compose("fit", editable, language_line=f"Write the explanation in {_language(lang)}.")
    prompt = (
        f"# Job seeker profile\n\n{profile_md.strip()}\n\n# Job posting\n\n{posting_block(posting)}\n\n"
        "Rate the fit now."
    )
    return system, [Message("user", [prompt])]


def parse_answer(text: str) -> tuple[str, str] | None:
    """First JSON object in `text` (fences, prose and `<think>` blocks tolerated) -> (rating, explanation) if valid."""
    text = _THINK.sub("", text or "")
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        rating, explanation = obj.get("rating"), obj.get("explanation")
        if rating in RATINGS and isinstance(explanation, str) and explanation.strip():
            return rating, explanation.strip()
        return None  # the first object decides
    return None


def evaluate(session_factory: sessionmaker[Session], posting_id: int, lang: str) -> FitResult:
    with session_factory() as session:
        profile = session.get(UserProfile, 1)
        markdown = (profile.profile_markdown or "") if profile else ""
        version = profile.version if profile else 0
        if not markdown.strip():
            raise ConflictError("profile_missing", "There is no user profile to evaluate against", {})
        posting = session.get(Posting, posting_id)
        if posting is None:
            raise NotFoundError("posting_not_found", "Posting not found", {"posting_id": posting_id})
        system, messages = build_messages(markdown, posting, lang, prompts.editable_text(session, "fit"))

    def first(_cfg: ConfigData) -> tuple[str, list[Message]]:
        return system, messages

    result, exceeded = None, False
    try:
        result, exceeded = llm_call(session_factory, PURPOSE, first, json_schema=FIT_SCHEMA, max_tokens=MAX_TOKENS)
    except UpstreamError as exc:  # the client got no usable text: same as an invalid answer
        if exc.code != "llm_invalid_output":
            raise  # an invalid answer is retried below
    parsed = parse_answer(result.text) if result else None
    if parsed is None:
        retry = messages if result is None else [
            *messages, Message("assistant", [result.text]), Message("user", [CORRECTION])
        ]

        def second(_cfg: ConfigData) -> tuple[str, list[Message]]:
            return system, retry

        result, exceeded_retry = llm_call(
            session_factory, PURPOSE, second, json_schema=FIT_SCHEMA, max_tokens=MAX_TOKENS
        )
        exceeded = exceeded or exceeded_retry
        parsed = parse_answer(result.text)
        if parsed is None:
            raise UpstreamError(
                "llm_invalid_output", "The LLM returned an unusable fit evaluation", {"reason": "invalid answer"}
            )
    return FitResult(parsed[0], parsed[1], version, exceeded)
