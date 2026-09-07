"""Text normalization for the schedule document.

The source file is Ukrainian and inconsistent in ways that break naive string matching:
``П`ятниця`` uses a backtick (U+0060) rather than an apostrophe, course headings mix Cyrillic
``І`` (U+0406) with Latin ``V``, and the filename itself is NFD-normalized. See BACKEND.md R8.
"""

from __future__ import annotations

import re
import unicodedata

# 0=Mon .. 6=Sun. Stored in canonical form; compare via ``normalize_text``.
DAY_NAMES = [
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]

DAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

# Verified to be 100% consistent across the document; the source of truth when Пара is blank (R6).
TIME_TO_PAIR = {
    "8.00": 1,
    "9.30": 2,
    "11.20": 3,
    "13.00": 4,
    "14.40": 5,
    "16.10": 6,
}

PAIR_TO_TIME = {pair: time for time, pair in TIME_TO_PAIR.items()}

DEFAULT_CLASS_MINUTES = 80

_APOSTROPHES = "`’ʼʹ‘´"
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_PUNCT = ".,;:)]}"


def normalize_text(value: str) -> str:
    """NFC-normalize, fold apostrophe variants, and collapse whitespace for comparison."""
    text = unicodedata.normalize("NFC", value or "")
    for char in _APOSTROPHES:
        text = text.replace(char, "'")
    return re.sub(r"\s+", " ", text).strip()


def day_index(value: str) -> int | None:
    """Map a Ukrainian day name to 0=Mon..6=Sun, tolerating apostrophe and case variants."""
    needle = normalize_text(value).casefold()
    if not needle:
        return None
    for index, name in enumerate(DAY_NAMES):
        if normalize_text(name).casefold() == needle:
            return index
    return None


def parse_time(value: str) -> str | None:
    """Convert the document's ``H.MM`` (or ``H:MM``) start time into canonical ``HH:MM``."""
    text = normalize_text(value)
    match = re.match(r"^(\d{1,2})[.:](\d{2})$", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return f"{hour:02d}:{minute:02d}"


def pair_from_time(value: str) -> int | None:
    """Infer the pair number from the start time (R6)."""
    text = normalize_text(value).replace(":", ".")
    if text in TIME_TO_PAIR:
        return TIME_TO_PAIR[text]
    canonical = parse_time(value)
    if canonical:
        hour, minute = canonical.split(":")
        return TIME_TO_PAIR.get(f"{int(hour)}.{minute}")
    return None


def add_minutes(hhmm: str, minutes: int) -> str:
    """Add minutes to an ``HH:MM`` string, clamping at the end of the day."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    total = min(hour * 60 + minute + minutes, 24 * 60 - 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def clean_url(value: str) -> str:
    """Strip punctuation that trails a URL when it was written inline in prose."""
    url = (value or "").strip()
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    return url


def find_urls(text: str) -> list[str]:
    return [clean_url(match) for match in _URL_RE.findall(text or "")]


def dedupe(values: list[str]) -> list[str]:
    """Order-preserving dedupe. Needed because every link appears twice (R3)."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def detect_provider(url: str | None) -> str:
    """Classify a meeting URL as ``zoom`` / ``google_meet`` / ``unknown``."""
    if not url:
        return "unknown"
    lowered = url.lower()
    if "meet.google.com" in lowered:
        return "google_meet"
    if "zoom.us" in lowered or "zoom.com" in lowered:
        return "zoom"
    return "unknown"


def is_teacher_line(line: str) -> bool:
    """Teacher names are the parenthesized line inside a cell (R9)."""
    text = normalize_text(line)
    return text.startswith("(") and text.endswith(")")


def strip_parens(line: str) -> str:
    text = normalize_text(line)
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


# Course headings are matched by ordinal position, never by literal string (R8), but the roman
# numeral is still useful for display.
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


def course_label(ordinal: int) -> str:
    """Human label for a 1-based course ordinal."""
    numeral = ROMAN[ordinal - 1] if 1 <= ordinal <= len(ROMAN) else str(ordinal)
    return f"{numeral} курс"
