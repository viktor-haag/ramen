import math
from typing import Protocol

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.errors import NotFoundError
from app.models import Application, Posting, PostingFit, PostingMatch, UserProfile
from app.schemas.feed import FeedFilter, FeedPage, PostingDetail, PostingOut
from app.schemas.fit import fit_out

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = 111.32


class GeocoderLike(Protocol):
    def lookup(self, place: str) -> tuple[float, float] | None: ...


def _like(column, text: str):
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.py_lower(column).like(f"%{escaped}%", escape="\\")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _base_query(f: FeedFilter) -> Select:
    stmt = select(Posting)
    if f.triage:
        stmt = stmt.where(Posting.triage_status.in_(f.triage))
    if f.source:
        stmt = stmt.where(Posting.source.in_(f.source))
    if f.profile_id is not None:
        stmt = stmt.where(
            select(PostingMatch.posting_id)
            .where(PostingMatch.posting_id == Posting.id, PostingMatch.profile_id == f.profile_id)
            .exists()
        )
    if f.q:
        stmt = stmt.where(
            or_(_like(Posting.title, f.q), _like(Posting.company, f.q), _like(Posting.description, f.q))
        )
    if f.found_after is not None:
        stmt = stmt.where(Posting.first_seen_at >= f.found_after)
    if f.found_before is not None:
        stmt = stmt.where(Posting.first_seen_at <= f.found_before)
    if f.published_after is not None:
        stmt = stmt.where(Posting.published_at >= f.published_after)
    if f.employment_type:
        stmt = stmt.where(Posting.employment_type == f.employment_type)
    if f.remote is not None:
        stmt = stmt.where(Posting.remote == f.remote)
    if f.fit:
        rated = [r for r in f.fit if r != "none"]
        pf = aliased(PostingFit)  # an alias: the fit sort joins PostingFit itself, which would correlate
        rating_of = select(pf.posting_id).where(pf.posting_id == Posting.id)
        wanted = []
        if rated:
            wanted.append(rating_of.where(pf.rating.in_(rated)).exists())
        if "none" in f.fit:  # no row, or a row that has no rating (yet)
            wanted.append(~rating_of.where(pf.rating.is_not(None)).exists())
        stmt = stmt.where(or_(*wanted))
    return stmt


def _ordered(stmt: Select, f: FeedFilter) -> Select:
    if f.sort == "fit":  # good -> moderate -> poor -> unrated, then newest first
        rank = case({"good": 0, "moderate": 1, "poor": 2}, value=PostingFit.rating, else_=3)
        return stmt.outerjoin(PostingFit, PostingFit.posting_id == Posting.id).order_by(
            rank, Posting.first_seen_at.desc(), Posting.id.desc()
        )
    column = getattr(Posting, f.sort)
    return stmt.order_by(column.desc().nulls_last(), Posting.id.desc())


def postings_out(session: Session, postings: list[Posting], detail: bool = False) -> list[PostingOut]:
    ids = [p.id for p in postings]
    profiles: dict[int, list[int]] = {}
    applications: dict[int, int] = {}
    fits: dict[int, PostingFit] = {}
    version = None
    if ids:
        profile = session.get(UserProfile, 1)
        version = profile.version if profile else None  # no profile row: nothing is outdated
        fits = {r.posting_id: r for r in session.scalars(select(PostingFit).where(PostingFit.posting_id.in_(ids)))}
        for posting_id, profile_id in session.execute(
            select(PostingMatch.posting_id, PostingMatch.profile_id)
            .where(PostingMatch.posting_id.in_(ids))
            .order_by(PostingMatch.profile_id)
        ):
            profiles.setdefault(posting_id, []).append(profile_id)
        applications = dict(
            session.execute(
                select(Application.posting_id, Application.id).where(Application.posting_id.in_(ids))
            ).all()
        )
    model = PostingDetail if detail else PostingOut
    skip = {"profile_ids", "application_id", "fit"}
    out = []
    for p in postings:
        values = {name: getattr(p, name) for name in model.model_fields if name not in skip}
        out.append(
            model(
                **values, profile_ids=profiles.get(p.id, []), application_id=applications.get(p.id),
                fit=fit_out(fits.get(p.id), version),
            )
        )
    return out


def get_posting(session: Session, posting_id: int) -> PostingDetail:
    posting = session.get(Posting, posting_id)
    if posting is None:
        raise NotFoundError("posting_not_found", "Posting not found", {"posting_id": posting_id})
    return postings_out(session, [posting], detail=True)[0]  # type: ignore[return-value]


def _radius_filter(stmt: Select, f: FeedFilter, center: tuple[float, float]) -> Select:
    """Bounding box in SQL (exact distance is checked in Python). Postings without coordinates cannot
    be placed, so they fall back to a text match on `location`."""
    lat0, lon0 = center
    radius = float(f.radius_km)
    dlat = radius / KM_PER_DEGREE
    cos_lat = max(math.cos(math.radians(lat0)), 0.01)
    dlon = min(radius / (KM_PER_DEGREE * cos_lat), 180.0)
    has_coords = and_(Posting.lat.is_not(None), Posting.lon.is_not(None))
    in_box = and_(
        has_coords,
        Posting.lat.between(lat0 - dlat, lat0 + dlat),
        Posting.lon.between(lon0 - dlon, lon0 + dlon),
    )
    return stmt.where(or_(in_box, and_(~has_coords, _like(Posting.location, f.location))))


def _within(p: Posting, center: tuple[float, float], radius: float) -> bool:
    return p.lat is None or p.lon is None or haversine_km(center[0], center[1], p.lat, p.lon) <= radius


def _geocode(f: FeedFilter, geocoder: GeocoderLike) -> tuple[float, float] | None:
    return geocoder.lookup(f.location) if f.location and f.radius_km else None


def matching_ids(session: Session, f: FeedFilter, geocoder: GeocoderLike) -> list[int]:
    """Ids of all postings the feed would list for `f` (offset and limit ignored), in feed order."""
    center = _geocode(f, geocoder)
    if center is None:
        stmt = _base_query(f)
        if f.location:
            stmt = stmt.where(_like(Posting.location, f.location))
        return list(session.scalars(_ordered(stmt, f).with_only_columns(Posting.id)))
    stmt = _radius_filter(_base_query(f), f, center)
    return [p.id for p in session.scalars(_ordered(stmt, f)) if _within(p, center, float(f.radius_km))]


def query_feed(session: Session, f: FeedFilter, geocoder: GeocoderLike) -> FeedPage:
    stmt = _base_query(f)
    center = _geocode(f, geocoder)

    if center is None:
        if f.location:
            stmt = stmt.where(_like(Posting.location, f.location))
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.scalars(_ordered(stmt, f).offset(f.offset).limit(f.limit)).all()
        return FeedPage(items=postings_out(session, list(rows)), total=total)

    stmt = _radius_filter(stmt, f, center)
    matched = [p for p in session.scalars(_ordered(stmt, f)) if _within(p, center, float(f.radius_km))]
    page = matched[f.offset : f.offset + f.limit]
    return FeedPage(items=postings_out(session, page), total=len(matched))
