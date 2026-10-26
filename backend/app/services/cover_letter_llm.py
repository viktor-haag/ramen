"""Cover letters: context blocks, prompt texts and answer validation for the `cover_letter` LLM.

All user/posting/document text is data: it is defused so it cannot open or close a data block.
No DB session is held during the LLM calls.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.errors import UnprocessableError, UpstreamError
from app.llm.base import Message
from app.llm.runner import llm_call
from app.models import Application, ProfileDocument, UserProfile
from app.services import prompts
from app.services.posting_text import DATA_TAGS, defuse, posting_block
from app.services.stream_filter import NOTE_MARKER

PURPOSE = "cover_letter"
DOC_CAP = 20_000
CONTEXT_CAP = 120_000
MAX_TOKENS = 8192

CORRECTION = (
    f"Your answer was not usable. Answer again with the complete document, then a line containing only "
    f"`{NOTE_MARKER}`, then 1-2 sentences for the user. The document must not be empty and must not be wrapped "
    "in code fences; for LaTeX it must be the complete source containing \\documentclass and \\end{document}."
)
REPAIR_INSTRUCTION = "The document does not compile; fix only the error, change nothing else."

LANGUAGE_LINES = {
    "de": "Write the letter in German.",
    "en": "Write the letter in English.",
}
AUTO_LANGUAGE_LINE = "Write the letter in the language of the posting."
FORMAT_LINES = {
    "latex": (
        "The document is the complete LaTeX source from `\\documentclass` to `\\end{document}`. Keep the preamble "
        "(everything before `\\begin{document}`) exactly as in the template. In the body use only commands and "
        "environments that appear in the template, plus basic text formatting (`\\textbf`, `\\textit`, `\\emph`, "
        "`\\underline`, `\\\\`, `\\par`, `\\hfill`, `\\vspace`, `\\href`, `\\url`, `itemize`/`enumerate`). "
        "Never define new commands and never read or write files."
    ),
    "text": "The document is the complete letter as plain text, no Markdown.",
}


@dataclass(frozen=True)
class Context:
    blocks: str
    missing_documents: list[str]
    missing_profile: bool


@dataclass(frozen=True)
class Answer:
    document: str
    note: str
    limit_exceeded: bool


def _data(text: str) -> str:
    return defuse(text, DATA_TAGS)


def build_context(session: Session, application: Application, ctx: dict) -> Context:
    blocks = [posting_block(application.posting, tags=DATA_TAGS)]
    missing_profile = False
    if ctx.get("profile"):
        profile = session.get(UserProfile, 1)
        markdown = ((profile.profile_markdown if profile else None) or "").strip()
        if markdown:
            blocks.append(f"<profile>\n{_data(markdown)}\n</profile>")
        else:
            missing_profile = True
    missing: list[str] = []
    for doc_id in ctx.get("document_ids") or []:
        doc = session.get(ProfileDocument, doc_id)
        if doc is None:
            missing.append(f"#{doc_id}")
            continue
        name = _data(doc.display_name or "").replace('"', "'")
        text = _data((doc.text or "").strip())
        body = text[:DOC_CAP]
        if len(text) > DOC_CAP:
            body += f"\n[Truncated: only the first {DOC_CAP} of {len(text)} characters are shown.]"
        blocks.append(f'<document name="{name}">\n{body}\n</document>')
    notes = (ctx.get("notes") or "").strip()
    if notes:
        blocks.append(f"<notes>\n{_data(notes)}\n</notes>")
    joined = "\n\n".join(blocks)
    if len(joined) > CONTEXT_CAP:
        raise UnprocessableError(
            "cover_letter_context_too_large",
            f"The selected context has {len(joined)} characters (maximum {CONTEXT_CAP})",
            {"chars": len(joined), "max": CONTEXT_CAP},
        )
    return Context(joined, missing, missing_profile)


def system(session: Session, fmt: str, language: str) -> str:
    return prompts.system_prompt(
        session,
        PURPOSE,
        language_line=LANGUAGE_LINES.get(language, AUTO_LANGUAGE_LINE),
        format_line=FORMAT_LINES["latex" if fmt == "latex" else "text"],
    )


def generate_text(ctx: Context, template: str | None) -> str:
    parts = [ctx.blocks]
    if template is not None:
        parts.append(f"<template>\n{_data(template)}\n</template>")
    parts.append("Write the cover letter now.")
    return "\n\n".join(parts)


def revise_text(ctx: Context, current: str, instruction: str) -> str:
    return "\n\n".join(
        [ctx.blocks, f"<current>\n{_data(current)}\n</current>", "Change the letter as follows: " + instruction]
    )


def repair_text(ctx: Context, current: str, log: str) -> str:
    return "\n\n".join(
        [ctx.blocks, f"<current>\n{_data(current)}\n</current>", f"<log>\n{_data(log)}\n</log>", REPAIR_INSTRUCTION]
    )


def forbidden_text(ctx: Context, current: str, command: str, line: int) -> str:
    return "\n\n".join(
        [
            ctx.blocks,
            f"<current>\n{_data(current)}\n</current>",
            f"Line {line} uses the forbidden {command}; remove or replace it, change nothing else.",
        ]
    )


_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"\A\s*```[A-Za-z]*[ \t]*\n(.*?)\n?```\s*\Z", re.DOTALL)


def parse_answer(text: str, fmt: str) -> tuple[str, str] | None:
    """Plain-text answer -> (document, note) if valid for `fmt` ("latex" or "text").

    Split at the last line that is (trimmed) `NOTE_MARKER`; without it the whole text is the document and
    the note is empty. `<think>` blocks and code fences around the document are removed.
    """
    text = _THINK.sub("", text or "")
    lines = text.split("\n")
    marks = [i for i, line in enumerate(lines) if line.strip() == NOTE_MARKER]
    if marks:
        document, note = "\n".join(lines[: marks[-1]]), "\n".join(lines[marks[-1] + 1:])
    else:
        document, note = text, ""
    fenced = _FENCE.match(document)
    document = (fenced.group(1) if fenced else document).strip()
    if not document:
        return None
    if fmt == "latex" and not ("\\documentclass" in document and "\\end{document}" in document):
        return None
    return document, note.strip()


def ask(
    session_factory: sessionmaker[Session],
    system: str,
    user_text: str,
    fmt: str,
    *,
    on_text: Callable[[str], None] | None = None,
    on_attempt: Callable[[], None] | None = None,
) -> Answer:
    """One LLM call plus at most one correction retry. `on_attempt()` runs before each try, `on_text`
    receives the streamed chunks (passed through to `llm_call`)."""
    messages = [Message("user", [user_text])]

    def call(conversation: list[Message]):
        if on_attempt is not None:
            on_attempt()
        return llm_call(
            session_factory, PURPOSE, lambda _cfg: (system, conversation), max_tokens=MAX_TOKENS, on_text=on_text
        )

    result, exceeded = None, False
    try:
        result, exceeded = call(messages)
    except UpstreamError as exc:  # no usable text: same as an invalid answer
        if exc.code != "llm_invalid_output":
            raise
    parsed = parse_answer(result.text, fmt) if result else None
    if parsed is None:
        retry = messages if result is None else [
            *messages, Message("assistant", [result.text]), Message("user", [CORRECTION])
        ]
        result, exceeded_retry = call(retry)
        exceeded = exceeded or exceeded_retry
        parsed = parse_answer(result.text, fmt)
        if parsed is None:
            raise UpstreamError(
                "llm_invalid_output", "The LLM returned an unusable cover letter", {"reason": "invalid answer"}
            )
    return Answer(parsed[0], parsed[1], exceeded)
