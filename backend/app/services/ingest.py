from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models import Posting, PostingMatch, SearchProfile
from app.plugins.base import JobPosting

# Content columns refreshed on every sighting. first_seen_at, triage_status and
# triaged_at are deliberately absent: they are never overwritten on conflict.
_CONTENT_FIELDS = (
    "url", "title", "company", "location", "lat", "lon", "description",
    "published_at", "employment_type", "remote", "contract_type", "raw",
)


@dataclass
class IngestResult:
    new_count: int
    total_count: int
    invalid_count: int
    new_ids: list[int] = field(default_factory=list)  # exactly the postings counted in new_count


def upsert_posting(session: Session, posting: JobPosting, now: datetime) -> tuple[Posting, bool]:
    """Insert or refresh one validated posting. Returns (row, created).

    created is decided atomically by the upsert itself: RETURNING yields the stored
    first_seen_at, which equals `now` only if this statement inserted the row.
    """
    values = posting.model_dump(include=set(_CONTENT_FIELDS))
    published = values["published_at"]
    if published is not None and published.tzinfo is None:
        values["published_at"] = published.replace(tzinfo=UTC)

    stmt = insert(Posting).values(
        source=posting.source,
        external_id=posting.external_id,
        first_seen_at=now,
        last_seen_at=now,
        **values,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={**{f: stmt.excluded[f] for f in _CONTENT_FIELDS}, "last_seen_at": now},
    ).returning(Posting.id, Posting.first_seen_at)
    posting_id, first_seen_at = session.execute(stmt).one()

    # Core upsert bypasses the identity map: drop any stale loaded copy.
    cached = session.identity_map.get(session.identity_key(Posting, posting_id))
    if cached is not None:
        session.expire(cached)
    return session.get(Posting, posting_id), first_seen_at == now


def _passes_filter(profile: SearchProfile, posting: JobPosting) -> bool:
    for field in ("employment_type", "remote"):
        wanted = getattr(profile, field)
        actual = getattr(posting, field)
        if wanted is not None and actual is not None and actual != wanted:
            return False
    return True


def ingest(
    session: Session, *, profile: SearchProfile, source: str, items: list[dict], now: datetime
) -> IngestResult:
    """Upsert plugin results for one profile. The caller commits."""
    new_count = total_count = invalid_count = 0
    new_ids: list[int] = []
    seen: set[str] = set()
    for item in items:
        try:
            posting = JobPosting.model_validate({**item, "source": source})
        except (ValidationError, TypeError):
            invalid_count += 1
            continue
        if posting.external_id in seen:
            continue
        seen.add(posting.external_id)
        if not _passes_filter(profile, posting):
            continue
        row, created = upsert_posting(session, posting, now)
        total_count += 1
        new_count += created
        if created:
            new_ids.append(row.id)
        session.execute(
            insert(PostingMatch)
            .values(posting_id=row.id, profile_id=profile.id, matched_at=now)
            .on_conflict_do_nothing()
        )
    return IngestResult(new_count, total_count, invalid_count, new_ids)
