import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ConflictError
from app.models import (
    Appointment,
    Application,
    AppSetting,
    Attachment,
    Contact,
    LLMConfig,
    LLMPurpose,
    LLMUsage,
    PluginSetting,
    Posting,
    PostingFit,
    PostingMatch,
    ProfileDocument,
    RunStatus,
    SearchProfile,
    SearchRun,
    StatusChange,
    UserProfile,
)
from app.services import profile_docs

log = logging.getLogger(__name__)

# Children before parents, so every reported count is the rows the table really had.
_RESET_ORDER = (
    ("posting_fit", PostingFit),
    ("posting_match", PostingMatch),
    ("status_change", StatusChange),
    ("appointment", Appointment),
    ("contact", Contact),
    ("attachment", Attachment),
    ("application", Application),
    ("job_posting", Posting),
    ("search_run", SearchRun),
    ("search_profile", SearchProfile),
    ("plugin_setting", PluginSetting),
    ("llm_usage", LLMUsage),
    ("llm_purpose", LLMPurpose),
    ("llm_config", LLMConfig),
    ("app_setting", AppSetting),
    ("profile_document", ProfileDocument),
    ("user_profile", UserProfile),
)


def _ensure_no_active_runs(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(SearchRun).where(SearchRun.status == RunStatus.running)):
        raise ConflictError("runs_active", "Search runs are active", {})


def clear_feed(session: Session) -> dict[str, int]:
    """Delete postings without an application (and their matches) and all search runs."""
    _ensure_no_active_runs(session)
    has_application = exists().where(Application.posting_id == Posting.id)
    postings = session.execute(delete(Posting).where(~has_application)).rowcount  # matches cascade
    runs = session.execute(delete(SearchRun)).rowcount
    return {"deleted_postings": postings, "deleted_runs": runs}


def reset_all(session: Session) -> dict[str, dict[str, int]]:
    """Delete all data (caller commits, then calls `clear_attachments_dir`)."""
    _ensure_no_active_runs(session)
    counts: dict[str, int] = {}
    for name, model in _RESET_ORDER:
        counts[name] = session.execute(delete(model)).rowcount
    return {"deleted": counts}


def delete_profile(session: Session) -> tuple[dict[str, int], list[str]]:
    """Delete all profile documents, the profile row and all fit evaluations (caller commits, then calls `discard_profile_files`).

    LLM configs, purposes, settings and usage stay. Returns the result and the stored paths to remove.
    """
    # Kept for consistency with the other destructive actions and because B2 evaluates postings against the
    # profile automatically after runs: deleting it under a running search would leave half-evaluated results.
    _ensure_no_active_runs(session)
    stored_paths = list(session.scalars(select(ProfileDocument.stored_path)))
    session.execute(delete(ProfileDocument))
    session.execute(delete(UserProfile))
    fits = session.execute(delete(PostingFit)).rowcount  # evaluations without a profile are meaningless
    return {"deleted_documents": len(stored_paths), "deleted_fits": fits}, stored_paths


def discard_profile_files(settings: Settings, stored_paths: list[str]) -> None:
    """Best effort, like `clear_attachments_dir`: the rows are already gone."""
    for stored in stored_paths:
        try:
            profile_docs.resolve_path(settings, stored).unlink(missing_ok=True)
        except (OSError, ValueError):
            log.warning("Could not remove profile document file %s", stored, exc_info=True)


def clear_attachments_dir(attachments_dir: Path) -> None:
    """Best effort: a locked file (e.g. open on Windows) must not fail a reset that already committed."""
    if not attachments_dir.is_dir():
        return
    for entry in attachments_dir.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not remove directory entry %s", entry, exc_info=True)
