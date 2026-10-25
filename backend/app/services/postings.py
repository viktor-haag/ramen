import uuid
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import NotFoundError, UpstreamError
from app.models import Application, PluginSetting, Posting
from app.plugins.base import JobPosting
from app.plugins.registry import PluginRegistry
from app.runner.failures import failure_text, split_timeout
from app.runner.pool import RunnerPool
from app.schemas.feed import ManualPostingIn, PostingOut
from app.services.feed import postings_out
from app.services.ingest import upsert_posting
from app.services.triage import save_posting


def create_manual(session: Session, data: ManualPostingIn, now: datetime) -> Application:
    """Create a manual posting and immediately save it (application status `saved`)."""
    posting = Posting(
        source="manual",
        external_id=uuid.uuid4().hex,
        first_seen_at=now,
        last_seen_at=now,
        **data.model_dump(),
    )
    session.add(posting)
    session.flush()
    return save_posting(session, posting.id, now)


def fetch_from_url(
    session: Session, registry: PluginRegistry, pool: RunnerPool, url: str, now: datetime
) -> PostingOut:
    """Fetch one posting via the plugin matching `url` and upsert it. The caller commits."""
    url = url.strip()
    info = registry.for_url(url)
    setting = session.get(PluginSetting, info.name) if info is not None else None
    if info is None or not (setting.enabled if setting is not None else info.enabled_by_default):
        raise NotFoundError("no_plugin_for_url", "No plugin can handle this URL", {"url": url})
    timeout, plugin_settings = split_timeout(info, setting.settings if setting is not None else None)

    try:
        item = pool.submit_fetch(info, url, plugin_settings, timeout).result()
        posting = JobPosting.model_validate({**item, "source": info.name})
    except ValidationError:
        raise UpstreamError(
            "fetch_failed", "Fetching the posting failed", {"reason": "Plugin returned an invalid posting"}
        ) from None
    except Exception as exc:
        reason = failure_text(exc, timeout)
        raise UpstreamError("fetch_failed", f"Fetching the posting failed: {reason}", {"reason": reason}) from exc

    row, _ = upsert_posting(session, posting, now)
    session.flush()
    return postings_out(session, [row])[0]
