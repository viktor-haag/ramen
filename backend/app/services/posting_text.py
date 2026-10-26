"""Shared rendering of a posting for LLM prompts (fit evaluation, cover letters).

Posting text is untrusted: it must not be able to open or close any of the data blocks a prompt uses,
so `defuse` swaps the `<` of those tags for a lookalike.
"""
import re

from app.models import Posting

DESCRIPTION_CAP = 12_000
DATA_TAGS = ("posting", "profile", "document", "notes", "template", "current", "log")


def _remote(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def defuse(text: str, tags: tuple[str, ...]) -> str:
    """Swap the `<` of every opening/closing `tags` tag start for a lookalike (case-insensitive, spaces allowed)."""
    pattern = re.compile(r"<\s*/?\s*(?:" + "|".join(re.escape(t) for t in tags) + r")\b", re.IGNORECASE)
    return pattern.sub(lambda m: "‹" + m.group(0)[1:], text)


def posting_block(posting: Posting, tags: tuple[str, ...] = ("posting",)) -> str:
    def val(v: str | None) -> str:
        return defuse((v or "").strip(), tags) or "unknown"

    lines = [
        f"Title: {val(posting.title)}",
        f"Company: {val(posting.company)}",
        f"Location: {val(posting.location)}",
        f"Employment type: {val(posting.employment_type)}",
        f"Remote: {_remote(posting.remote)}",
        f"Contract type: {val(posting.contract_type)}",
    ]
    description = defuse((posting.description or "").strip(), tags)
    if not description:
        lines.append("Description: (no description available; judge from the key facts above and say so)")
    else:
        body = description[:DESCRIPTION_CAP]
        if len(description) > DESCRIPTION_CAP:
            body += (
                f"\n[Truncated: only the first {DESCRIPTION_CAP} of {len(description)} characters are shown.]"
            )
        lines.append("Description:\n" + body)
    return "<posting>\n" + "\n".join(lines) + "\n</posting>"
