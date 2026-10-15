from enum import StrEnum


class SessionStatus(StrEnum):
    PENDING = "pending"
    TRANSCRIBED = "transcribed"
    SYNTHESISED = "synthesised"


class JobStatus(StrEnum):
    """Status of work that may run in the background: transcripts and narratives."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriptSource(StrEnum):
    AUDIO = "audio"
    MANUAL = "manual"


class NarrativeFormat(StrEnum):
    MEMOIR = "memoir"
    LETTER = "letter"
    TIMELINE = "timeline"


class ThreadType(StrEnum):
    NEW = "new"
    CONTINUATION = "continuation"
    REHEARSED = "rehearsed"
