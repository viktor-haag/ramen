from enum import StrEnum


class TriageStatus(StrEnum):
    new = "new"
    saved = "saved"
    dismissed = "dismissed"


class AppStatus(StrEnum):
    saved = "saved"
    preparing = "preparing"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"
    accepted = "accepted"


ACTIVE_STATUSES = frozenset(
    {AppStatus.saved, AppStatus.preparing, AppStatus.applied, AppStatus.interviewing, AppStatus.offer}
)
TERMINAL_STATUSES = frozenset({AppStatus.rejected, AppStatus.withdrawn, AppStatus.accepted})


class RunStatus(StrEnum):
    running = "running"
    ok = "ok"
    error = "error"
    timeout = "timeout"


class RunTrigger(StrEnum):
    manual = "manual"
    schedule = "schedule"


class AppointmentKind(StrEnum):
    deadline = "deadline"
    interview = "interview"
    other = "other"


class AttachmentKind(StrEnum):
    cv = "cv"
    cover_letter = "cover_letter"
    other = "other"


class LLMProvider(StrEnum):
    anthropic = "anthropic"
    openai = "openai"
    openai_compatible = "openai_compatible"


class ThinkingLevel(StrEnum):
    off = "off"
    low = "low"
    medium = "medium"
    high = "high"
    max = "max"


class LLMPurposeKind(StrEnum):
    profile = "profile"
    fit = "fit"
    extraction = "extraction"
    cover_letter = "cover_letter"


class DocumentKind(StrEnum):
    text = "text"
    pdf_text = "pdf_text"
    pdf_scan = "pdf_scan"
    image = "image"


class TextSource(StrEnum):
    extracted = "extracted"
    llm = "llm"
    manual = "manual"


class FitRating(StrEnum):
    good = "good"
    moderate = "moderate"
    poor = "poor"


class FitStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


class CoverLetterFormat(StrEnum):
    latex = "latex"
    text = "text"


class CoverLetterLanguage(StrEnum):
    posting = "posting"
    de = "de"
    en = "en"


class CoverLetterStatus(StrEnum):
    idle = "idle"
    generating = "generating"
    compiling = "compiling"


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
