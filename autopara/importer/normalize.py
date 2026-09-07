"""Text normalization for the schedule document.

The source file is Ukrainian and inconsistent in ways that break naive string matching:
``П`ятниця`` uses a backtick (U+0060) rather than an apostrophe, course headings mix Cyrillic
``І`` (U+0406) with Latin ``V``, and the filename itself is NFD-normalized. See BACKEND.md R8.

The document is *not* required to be Ukrainian. Day names are recognised through a multilingual
alias table (BACKEND.md R10) and everything the app generates from them -- day labels, course
names -- is emitted in Ukrainian, so a Polish or English timetable still produces a Ukrainian
schedule.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

# 0=Mon .. 6=Sun. Stored in canonical Ukrainian form; compare via ``day_index``.
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

# Pairs 1-6 are the university's own slots, verified to be 100% consistent across the document;
# they are the source of truth when Пара is blank (R6).
#
# Pairs 7-10 continue the same 80-minute + 10-minute-break rhythm into the evening. The document
# never uses them. They exist so the week grid covers 08:00 through 23:00 and a class can be
# created at any time of day, which is why they must not be treated as "real" academic pairs
# anywhere: ACADEMIC_PAIRS is what a parsed lesson is expected to fall inside.
TIME_TO_PAIR = {
    "8.00": 1,
    "9.30": 2,
    "11.20": 3,
    "13.00": 4,
    "14.40": 5,
    "16.10": 6,
    "17.40": 7,
    "19.10": 8,
    "20.40": 9,
    "22.10": 10,
}

ACADEMIC_PAIRS = 6

PAIR_TO_TIME = {pair: time for time, pair in TIME_TO_PAIR.items()}

DEFAULT_CLASS_MINUTES = 80

_APOSTROPHES = "`’ʼʹ‘´"
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_PUNCT = ".,;:)]}"
_CLOCK_RE = re.compile(r"(\d{1,2})\s*[.:]\s*(\d{2})")


def normalize_text(value: str) -> str:
    """NFC-normalize, fold apostrophe variants, and collapse whitespace for comparison."""
    text = unicodedata.normalize("NFC", value or "")
    for char in _APOSTROPHES:
        text = text.replace(char, "'")
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------- day names

# R10: the importer accepts any language. Aliases are matched after ``normalize_text`` +
# casefold, longest first, so "Понеділок 1" or "Monday" both resolve. Ambiguous two-letter
# abbreviations shared between languages (German "so" = Sonntag vs Polish "sob" = sobota) are
# deliberately left out rather than guessed at.
_DAY_ALIASES: dict[str, int] = {}


def _register(index: int, *names: str) -> None:
    for name in names:
        _DAY_ALIASES[normalize_text(name).casefold()] = index


_register(0, "понеділок", "понеділка", "пн", "понедельник", "monday", "mon", "poniedzialek",
          "poniedziałek", "montag", "lunes", "lundi", "lunedi", "lunedì", "luni")
_register(1, "вівторок", "вт", "вторник", "tuesday", "tue", "tues", "wtorek", "dienstag",
          "martes", "mardi", "martedi", "martedì", "marti")
_register(2, "середа", "середи", "ср", "среда", "wednesday", "wed", "sroda", "środa",
          "mittwoch", "miercoles", "miércoles", "mercredi", "mercoledi", "mercoledì")
_register(3, "четвер", "чт", "четверг", "thursday", "thu", "thur", "thurs", "czwartek",
          "donnerstag", "jueves", "jeudi", "giovedi", "giovedì", "joi")
_register(4, "п'ятниця", "п'ятниці", "пт", "пятница", "friday", "fri", "piatek", "piątek",
          "freitag", "viernes", "vendredi", "venerdi", "venerdì", "vineri")
_register(5, "субота", "сб", "суббота", "saturday", "sat", "sobota", "samstag", "sonnabend",
          "sabado", "sábado", "samedi", "sabato", "sambata", "sâmbătă")
_register(6, "неділя", "нд", "вс", "воскресенье", "sunday", "sun", "niedziela", "sonntag",
          "domingo", "dimanche", "domenica", "duminica", "duminică")

# Longest first so "субота" wins over the shorter "сб" when a cell holds extra text.
_ALIASES_BY_LENGTH = sorted(_DAY_ALIASES, key=len, reverse=True)


def _day_key(value: str) -> str:
    text = normalize_text(value).casefold()
    return text.strip(" .,:;-–—()[]")


def day_index(value: str) -> int | None:
    """Map a day name in any supported language to 0=Mon..6=Sun (R8, R10)."""
    needle = _day_key(value)
    if not needle:
        return None
    if needle in _DAY_ALIASES:
        return _DAY_ALIASES[needle]
    # A cell may carry more than the bare name ("Понеділок 02.09"); match on its opening word.
    for alias in _ALIASES_BY_LENGTH:
        if len(alias) >= 3 and needle.startswith(alias):
            return _DAY_ALIASES[alias]
    return None


def day_name(index: int) -> str:
    """The Ukrainian name for a weekday index, whatever language the document used."""
    return DAY_NAMES[index % 7]


def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


# ------------------------------------------------------------------------- times


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


def parse_time_range(value: str) -> tuple[str | None, str | None]:
    """Pull a start and an optional end time out of a Час cell, in any language.

    Timetables from other tooling write the slot as ``8.00-9.20`` rather than a bare start time;
    when an end time is present it beats the assumed class duration.
    """
    text = normalize_text(value)
    found: list[str] = []
    for raw_hour, raw_minute in _CLOCK_RE.findall(text):
        hour, minute = int(raw_hour), int(raw_minute)
        if 0 <= hour < 24 and 0 <= minute < 60:
            found.append(f"{hour:02d}:{minute:02d}")
    start = found[0] if found else None
    end = found[1] if len(found) > 1 and found[1] > found[0] else None
    return start, end


def pair_from_time(value: str) -> int | None:
    """Infer the pair number from the start time (R6). Exact grid slots only."""
    text = normalize_text(value).replace(":", ".")
    if text in TIME_TO_PAIR:
        return TIME_TO_PAIR[text]
    canonical = parse_time(value)
    if canonical:
        hour, minute = canonical.split(":")
        return TIME_TO_PAIR.get(f"{int(hour)}.{minute}")
    return None


def pair_start_time(pair: int) -> str:
    """Canonical ``HH:MM`` start of a pair number."""
    raw = PAIR_TO_TIME.get(pair)
    if not raw:
        return ""
    hour, minute = raw.split(".")
    return f"{int(hour):02d}:{minute}"


def pair_slot(hhmm: str) -> int:
    """Which grid row an arbitrary ``HH:MM`` belongs in.

    Manually entered and dragged classes are not restricted to the standard slots, but the week
    grid has a fixed set of rows, so every time has to land in one. The slot is the last one that
    has already begun; anything before the first slot uses row 1.
    """
    exact = pair_from_time(hhmm)
    if exact:
        return exact
    slot = 1
    for pair in sorted(PAIR_TO_TIME):
        if pair_start_time(pair) <= hhmm:
            slot = pair
    return slot


def add_minutes(hhmm: str, minutes: int) -> str:
    """Add minutes to an ``HH:MM`` string, clamping at the end of the day."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    total = min(hour * 60 + minute + minutes, 24 * 60 - 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def minutes_between(start: str, end: str) -> int:
    """Length in minutes of an ``HH:MM`` .. ``HH:MM`` range."""

    def as_minutes(value: str) -> int:
        hour, minute = (int(part) for part in value.split(":"))
        return hour * 60 + minute

    return max(0, as_minutes(end) - as_minutes(start))


# -------------------------------------------------------------------------- urls


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


# Course headings are matched by ordinal position, never by literal string (R8). The label the app
# stores is always Ukrainian, whatever the document said (R10).
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]

# Words that mark a "year of study" heading across the languages the importer accepts. Used only
# to recognise a heading paragraph -- the stored name is always ``course_label``.
_COURSE_WORDS = ("курс", "kurs", "course", "year", "rok", "jahrgang", "año", "ano", "anno")


def is_course_heading(text: str) -> bool:
    words = normalize_text(text).casefold().split()
    return any(word.strip(".,:;") in _COURSE_WORDS for word in words)


def course_label(ordinal: int) -> str:
    """Human label for a 1-based course ordinal, always in Ukrainian (R10)."""
    numeral = ROMAN[ordinal - 1] if 1 <= ordinal <= len(ROMAN) else str(ordinal)
    return f"{numeral} курс"
