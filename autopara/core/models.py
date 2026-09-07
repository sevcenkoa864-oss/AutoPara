"""Dataclasses shared between storage, scheduler and UI.

These mirror the SQLite schema documented in docs/BACKEND.md section 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

# Occurrence lifecycle.
STATUS_OPENED = "opened"   # auto-opened by the scheduler at (start - lead)
STATUS_MANUAL = "manual"   # the user opened it, from a card click or a catch-up notification
STATUS_MISSED = "missed"   # the class ended before anything opened it
STATUS_SKIPPED = "skipped" # the user dismissed it

PROVIDER_ZOOM = "zoom"
PROVIDER_MEET = "google_meet"
PROVIDER_UNKNOWN = "unknown"

CATCHUP_NOTIFY = "notify"
CATCHUP_OPEN = "open"
CATCHUP_MISSED = "missed"


def parse_hhmm(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


@dataclass
class Course:
    id: int
    ordinal: int
    name: str


@dataclass
class Group:
    id: int
    course_id: int
    name: str
    specialty: str
    col_lo: int
    col_hi: int


@dataclass
class Lesson:
    id: int
    course_id: int
    day_index: int          # 0=Mon .. 6=Sun
    pair: int               # 1..6
    start_time: str         # 'HH:MM'
    end_time: str           # 'HH:MM'
    subject: str
    teacher: str = ""
    url: str | None = None
    provider: str = PROVIDER_UNKNOWN
    needs_link: bool = False
    is_manual: bool = False
    source_key: str = ""
    group_names: list[str] = field(default_factory=list)

    @property
    def start(self) -> time:
        return parse_hhmm(self.start_time)

    @property
    def end(self) -> time:
        return parse_hhmm(self.end_time)

    @property
    def pair_span(self) -> int:
        """How many consecutive pairs this lesson covers (a vMerge block covers several)."""
        from ..importer.normalize import TIME_TO_PAIR

        last = self.pair
        for raw_time, pair in TIME_TO_PAIR.items():
            hour, minute = raw_time.split(".")
            slot = f"{int(hour):02d}:{minute}"
            if self.start_time <= slot < self.end_time:
                last = max(last, pair)
        return max(1, last - self.pair + 1)

    def starts_on(self, day: date) -> datetime:
        return datetime.combine(day, self.start)

    def ends_on(self, day: date) -> datetime:
        return datetime.combine(day, self.end)

    def time_range(self) -> str:
        return f"{self.start_time}–{self.end_time}"


@dataclass
class Occurrence:
    id: int
    lesson_id: int
    occur_date: str  # 'YYYY-MM-DD'
    status: str
    fired_at: str


@dataclass
class Settings:
    """Typed view over the ``settings`` key/value table."""

    selected_course_id: int | None = None
    selected_group_id: int | None = None
    lead_minutes: int = 1
    class_duration_minutes: int = 80
    autostart_enabled: bool = False
    catchup_mode: str = CATCHUP_NOTIFY
    last_import_path: str = ""
