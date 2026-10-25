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

from app.plugins.base import JobPosting

CORE = {"id", "job_url", "title", "company", "location", "description", "date_posted", "is_remote"}
TEMPORARY_TYPES = {"contract", "temporary", "internship"}


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
    if isinstance(value, (bool, int, float, str)):
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
        description=_text(row.get("description")),
        published_at=_published(row.get("date_posted")),
        employment_type=employment,
        remote=bool(remote) if remote is not None else None,
        contract_type="temporary" if types & TEMPORARY_TYPES else None,
        raw=raw,
    )
