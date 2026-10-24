"""Pure helpers of the Arbeitnow plugin: keyword matching, HTML to text, mapping to ``JobPosting``.

All API field names live in the ``F_*`` constants below: API drift is a one-spot fix.
"""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

from app.plugins.base import JobPosting

SOURCE = "arbeitnow"

# --- response field names (per job) -----------------------------------------------------
F_SLUG = "slug"
F_TITLE = "title"
F_COMPANY = "company_name"
F_DESCRIPTION = "description"  # HTML
F_REMOTE = "remote"
F_URL = "url"
F_TAGS = "tags"
F_JOB_TYPES = "job_types"
F_LOCATION = "location"
F_CREATED_AT = "created_at"  # Unix seconds


def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole word / word sequence, case-insensitive; whitespace in the keyword matches any whitespace."""
    parts = keyword.split()
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, parts)) + r"(?!\w)", re.IGNORECASE)


_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def _break(self) -> None:
        """Start a new line unless the text already ends with one (keeps tag soup from piling up blanks)."""
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        # A block tag right after a list bullet ("<li><p>") stays on the bullet's line.
        after_bullet = bool(self.parts) and self.parts[-1] == "- "
        if tag in _BLOCK_TAGS and (tag == "li" or not after_bullet):
            self._break()
        if tag == "li":
            self.parts.append("- ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS and tag != "br":
            self._break()

    def handle_data(self, data):
        self.parts.append(data)


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def html_to_text(html: str | None) -> str | None:
    """Convert an HTML description to plain text; empty result -> ``None``.

    About a fifth of the live descriptions are entity-escaped HTML (``&lt;p&gt;...``); one pass leaves
    literal tags behind, so the conversion runs exactly once more if the result still contains tags.
    """
    text = _convert(html)
    if text and _TAG_RE.search(text):
        text = _convert(text)
    return text


def _convert(html: str | None) -> str | None:
    if not html:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines: list[str] = []
    for line in "".join(parser.parts).split("\n"):
        line = line.strip()
        if line == "-":  # empty list item
            line = ""
        if not line and (not lines or not lines[-1]):
            continue  # collapse runs of blank lines (and drop leading ones)
        lines.append(line)
    text = "\n".join(lines).strip()
    return text or None


def title_and_tags(item: dict) -> str:
    """Title, then each tag on its own line (the text a keyword is matched against besides the description)."""
    tags = item.get(F_TAGS)
    tag_list = [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []
    return "\n".join([str(item.get(F_TITLE) or ""), *tag_list])


def _types_text(job_types) -> str:
    if not isinstance(job_types, list):
        return ""
    return " ".join(str(t) for t in job_types).casefold()


def _one_of(text: str, a: tuple[str, ...], b: tuple[str, ...], a_value: str, b_value: str) -> str | None:
    has_a = any(k in text for k in a)
    has_b = any(k in text for k in b)
    if has_a == has_b:
        return None
    return a_value if has_a else b_value


def employment_type(job_types) -> str | None:
    return _one_of(
        _types_text(job_types),
        ("full time", "full-time", "fulltime", "vollzeit"),
        ("part time", "part-time", "parttime", "teilzeit"),
        "fulltime",
        "parttime",
    )


def contract_type(job_types) -> str | None:
    text = _types_text(job_types)
    has_permanent = any(k in text for k in ("unbefristet", "permanent", "indefinite", "cdi"))
    # "unbefristet" contains "befristet", so it is removed before looking for temporary markers.
    has_temporary = any(k in text.replace("unbefristet", "") for k in ("befristet", "fixed term", "temporary", "cdd"))
    if has_permanent == has_temporary:  # both or neither
        return None
    return "permanent" if has_permanent else "temporary"


def _published_at(value) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _text_or_none(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def to_posting(item: dict, description: str | None, coords: tuple[float, float] | None) -> JobPosting | None:
    """Map one feed item; ``None`` if ``slug`` or ``title`` is missing or empty."""
    slug = _text_or_none(item.get(F_SLUG))
    title = _text_or_none(item.get(F_TITLE))
    if slug is None or title is None:
        return None
    remote = item.get(F_REMOTE)
    job_types = item.get(F_JOB_TYPES)
    return JobPosting(
        source=SOURCE,
        external_id=slug,
        url=str(item.get(F_URL) or ""),
        title=title,
        company=_text_or_none(item.get(F_COMPANY)),
        location=_text_or_none(item.get(F_LOCATION)),
        lat=coords[0] if coords else None,
        lon=coords[1] if coords else None,
        description=description,
        published_at=_published_at(item.get(F_CREATED_AT)),
        employment_type=employment_type(job_types),
        remote=remote if isinstance(remote, bool) else None,
        contract_type=contract_type(job_types),
        raw=item,
    )
