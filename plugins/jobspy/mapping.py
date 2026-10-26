"""JobSpy result row (``DataFrame.to_dict("records")``) → ``JobPosting``.

Row format of python-jobspy 1.4.1 (``JobPost.model_dump()``): ``location`` is already a display
string ("City, State, Country"), ``job_type``/``emails``/``skills`` are comma-joined strings,
enums are plain values, ``date_posted`` is a ``datetime.date``. Missing values come back as
``None`` or, in string/float columns, as ``NaN`` (``NaT``/``pd.NA`` possible) – ``clean`` maps
them all to ``None``. No pandas import here (discovery must stay light).
"""

import datetime as dt
import hashlib
import math
import re
from html.parser import HTMLParser

from app.plugins.base import JobPosting

CORE = {"id", "job_url", "title", "company", "location", "description", "date_posted", "is_remote"}
TEMPORARY_TYPES = {"contract", "temporary", "internship"}


# HTML → text: copy of plugins/arbeitnow/mapping.py (plugins must not import each other; each one
# is loaded by module path in the worker processes). Keeps paragraphs, line breaks and list bullets.
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


def clean(value):
    """NaN/NaT/NA → None; numpy scalars → Python scalars."""
    if value is None:
        return None
    if type(value).__name__ in ("NaTType", "NAType"):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if type(value).__module__ == "numpy" and hasattr(value, "item"):
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    return value


def _text(value) -> str | None:
    value = clean(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _published(value) -> dt.datetime | None:
    value = clean(value)
    if isinstance(value, dt.datetime):  # also pandas.Timestamp
        value = value.date()
    elif isinstance(value, str):
        try:
            value = dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    if not isinstance(value, dt.date):
        return None
    return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)


def _location(value) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return ", ".join(p.strip() for p in text.split(",") if p.strip()) or None


def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None  # inf/-inf/nan are not valid JSON
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(clean(v)) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(clean(v)) for k, v in value.items()}
    return str(value)


def to_posting(row: dict, source: str) -> JobPosting | None:
    """None for rows without title or URL."""
    title, url = _text(row.get("title")), _text(row.get("job_url"))
    if not title or not url:
        return None
    types = {t.strip() for t in (_text(row.get("job_type")) or "").split(",") if t.strip()}
    employment = "fulltime" if "fulltime" in types else "parttime" if "parttime" in types else None
    remote = clean(row.get("is_remote"))
    raw = {}
    for key, value in row.items():
        if key in CORE:
            continue
        value = clean(value)
        if value is None or value == "" or value == []:
            continue
        raw[key] = _json_safe(value)
    return JobPosting(
        source=source,
        external_id=_text(row.get("id")) or hashlib.sha1(url.encode()).hexdigest()[:16],
        url=url,
        title=title,
        company=_text(row.get("company")),
        location=_location(row.get("location")),
        description=html_to_text(_text(row.get("description"))),
        published_at=_published(row.get("date_posted")),
        employment_type=employment,
        remote=bool(remote) if remote is not None else None,
        contract_type="temporary" if types & TEMPORARY_TYPES else None,
        raw=raw,
    )
