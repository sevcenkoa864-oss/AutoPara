"""SQLite persistence. The database is the single source of truth for the whole app.

The schema is documented in docs/BACKEND.md section 3. The one invariant worth restating here:
``occurrences`` carries ``UNIQUE(lesson_id, occur_date)`` and the scheduler inserts that row
*before* opening a browser, so "open each class exactly once" is enforced by the database rather
than by in-memory bookkeeping.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

import logging

from ..importer.schedule_parser import ParsedCourse
from .models import (
    CATCHUP_NOTIFY,
    THEME_SYSTEM,
    Course,
    Group,
    Lesson,
    Occurrence,
    Settings,
)

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS courses (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ordinal INTEGER NOT NULL UNIQUE,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    specialty TEXT NOT NULL DEFAULT '',
    col_lo    INTEGER NOT NULL DEFAULT 0,
    col_hi    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(course_id, name)
);

CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    day_index  INTEGER NOT NULL,
    pair       INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    teacher    TEXT NOT NULL DEFAULT '',
    url        TEXT,
    provider   TEXT NOT NULL DEFAULT 'unknown',
    needs_link INTEGER NOT NULL DEFAULT 0,
    is_manual  INTEGER NOT NULL DEFAULT 0,
    source_key TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lesson_groups (
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    group_id  INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (lesson_id, group_id)
);

CREATE TABLE IF NOT EXISTS occurrences (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id  INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    occur_date TEXT NOT NULL,
    status     TEXT NOT NULL,
    fired_at   TEXT NOT NULL,
    UNIQUE(lesson_id, occur_date)
);

CREATE INDEX IF NOT EXISTS idx_lessons_day ON lessons(day_index);
CREATE INDEX IF NOT EXISTS idx_occurrences_date ON occurrences(occur_date);
"""

_DEFAULTS = {
    "lead_minutes": "1",
    "class_duration_minutes": "80",
    # Autostart is on out of the box: the installer writes the same Run entry, and an app whose
    # whole purpose is to open classes while you are elsewhere is useless if it is not running.
    "autostart_enabled": "1",
    "catchup_mode": CATCHUP_NOTIFY,
    "last_import_path": "",
    "notifications_enabled": "1",
    "notify_minutes": "10",
    # Set on every import. The scheduler ignores anything that had already started by then --
    # see "The schedule starts when it is imported" in docs/BACKEND.md section 4.
    "schedule_active_from": "",
    "schedule_copy_path": "",
    # A fresh install follows the Windows app theme; the toolbar toggle pins light or dark.
    "theme": THEME_SYSTEM,
}


import sys


def default_db_path() -> Path:
    """Path to the SQLite database file: %APPDATA%\\AutoPara on Windows, Application Support on macOS."""
    if os.environ.get("APPDATA"):
        base = os.environ["APPDATA"]
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = str(Path.home())
    directory = Path(base) / "AutoPara"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "autopara.db"



def schedules_dir(db_path: str | Path | None = None) -> Path:
    """Where the imported ``.docx`` is kept.

    The app copies the document rather than remembering where it came from: the original is
    usually a download that gets tidied away, and losing it should not cost the user their ability
    to re-import. The copy lives beside the database, so uninstalling clears it with everything
    else while a reinstall leaves it alone.
    """
    directory = Path(db_path or default_db_path()).parent / "schedules"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class Storage:
    """Thin data-access layer over SQLite. All UI and scheduler reads go through this."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._seed_defaults()

    def close(self) -> None:
        self.connection.close()

    # ---------------------------------------------------------------- settings

    def _seed_defaults(self) -> None:
        for key, value in _DEFAULTS.items():
            self.connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
            )
        self.connection.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.connection.commit()

    def settings(self) -> Settings:
        def as_int(key: str, fallback: int) -> int:
            try:
                return int(self.get_setting(key) or fallback)
            except (TypeError, ValueError):
                return fallback

        course_id = self.get_setting("selected_course_id")
        group_id = self.get_setting("selected_group_id")
        return Settings(
            selected_course_id=int(course_id) if course_id else None,
            selected_group_id=int(group_id) if group_id else None,
            lead_minutes=as_int("lead_minutes", 1),
            class_duration_minutes=as_int("class_duration_minutes", 80),
            autostart_enabled=self.get_setting("autostart_enabled", "1") == "1",
            catchup_mode=self.get_setting("catchup_mode") or CATCHUP_NOTIFY,
            last_import_path=self.get_setting("last_import_path") or "",
            notifications_enabled=self.get_setting("notifications_enabled", "1") == "1",
            notify_minutes=as_int("notify_minutes", 10),
            theme=self.get_setting("theme") or THEME_SYSTEM,
            schedule_active_from=self.get_setting("schedule_active_from") or "",
            schedule_copy_path=self.get_setting("schedule_copy_path") or "",
        )

    # ----------------------------------------------------------------- courses

    def courses(self) -> list[Course]:
        rows = self.connection.execute("SELECT * FROM courses ORDER BY ordinal").fetchall()
        return [Course(id=r["id"], ordinal=r["ordinal"], name=r["name"]) for r in rows]

    def groups(self, course_id: int) -> list[Group]:
        rows = self.connection.execute(
            "SELECT * FROM groups WHERE course_id = ? ORDER BY col_lo", (course_id,)
        ).fetchall()
        return [
            Group(
                id=r["id"],
                course_id=r["course_id"],
                name=r["name"],
                specialty=r["specialty"],
                col_lo=r["col_lo"],
                col_hi=r["col_hi"],
            )
            for r in rows
        ]

    def course(self, course_id: int) -> Course | None:
        row = self.connection.execute(
            "SELECT * FROM courses WHERE id = ?", (course_id,)
        ).fetchone()
        if not row:
            return None
        return Course(id=row["id"], ordinal=row["ordinal"], name=row["name"])

    def group(self, group_id: int) -> Group | None:
        row = self.connection.execute(
            "SELECT * FROM groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not row:
            return None
        return Group(
            id=row["id"],
            course_id=row["course_id"],
            name=row["name"],
            specialty=row["specialty"],
            col_lo=row["col_lo"],
            col_hi=row["col_hi"],
        )

    # ------------------------------------------------------------------ import

    def import_courses(self, parsed: list[ParsedCourse], source_path: str = "") -> None:
        """Replace imported data while preserving manual lessons, occurrences and settings.

        Imported lessons are matched on ``source_key`` so a re-imported class keeps its row id --
        and therefore its occurrence history -- when the document is updated.
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN")
            for course in parsed:
                cursor.execute(
                    "INSERT INTO courses(ordinal, name) VALUES (?, ?) "
                    "ON CONFLICT(ordinal) DO UPDATE SET name = excluded.name",
                    (course.ordinal, course.name),
                )
                course_id = cursor.execute(
                    "SELECT id FROM courses WHERE ordinal = ?", (course.ordinal,)
                ).fetchone()["id"]

                group_ids: dict[str, int] = {}
                for group in course.groups:
                    cursor.execute(
                        "INSERT INTO groups(course_id, name, specialty, col_lo, col_hi) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(course_id, name) DO UPDATE SET "
                        "specialty = excluded.specialty, col_lo = excluded.col_lo, "
                        "col_hi = excluded.col_hi",
                        (course_id, group.name, group.specialty, group.col_lo, group.col_hi),
                    )
                    group_ids[group.name] = cursor.execute(
                        "SELECT id FROM groups WHERE course_id = ? AND name = ?",
                        (course_id, group.name),
                    ).fetchone()["id"]

                incoming_keys = {lesson.source_key(course.ordinal) for lesson in course.lessons}

                # Drop imported lessons that vanished from the document; keep manual ones.
                existing = cursor.execute(
                    "SELECT id, source_key FROM lessons WHERE course_id = ? AND is_manual = 0",
                    (course_id,),
                ).fetchall()
                for row in existing:
                    if row["source_key"] not in incoming_keys:
                        cursor.execute("DELETE FROM lessons WHERE id = ?", (row["id"],))

                for lesson in course.lessons:
                    key = lesson.source_key(course.ordinal)
                    found = cursor.execute(
                        "SELECT id FROM lessons WHERE course_id = ? AND source_key = ? "
                        "AND is_manual = 0",
                        (course_id, key),
                    ).fetchone()
                    values = (
                        course_id,
                        lesson.day_index,
                        lesson.pair,
                        lesson.start_time,
                        lesson.end_time,
                        lesson.subject,
                        lesson.teacher,
                        lesson.url,
                        lesson.provider,
                        int(lesson.needs_link),
                        key,
                    )
                    if found:
                        lesson_id = found["id"]
                        cursor.execute(
                            "UPDATE lessons SET course_id=?, day_index=?, pair=?, start_time=?, "
                            "end_time=?, subject=?, teacher=?, url=?, provider=?, needs_link=?, "
                            "source_key=? WHERE id=?",
                            (*values, lesson_id),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO lessons(course_id, day_index, pair, start_time, "
                            "end_time, subject, teacher, url, provider, needs_link, source_key) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            values,
                        )
                        lesson_id = cursor.lastrowid

                    cursor.execute(
                        "DELETE FROM lesson_groups WHERE lesson_id = ?", (lesson_id,)
                    )
                    for name in lesson.group_names:
                        if name in group_ids:
                            cursor.execute(
                                "INSERT OR IGNORE INTO lesson_groups(lesson_id, group_id) "
                                "VALUES (?, ?)",
                                (lesson_id, group_ids[name]),
                            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        # A new document replaces the week: every occurrence recorded against the old timetable
        # is discarded, so a fresh import starts from a clean grid rather than showing yesterday's
        # verdicts against today's classes.
        self.clear_occurrences()

        # A freshly imported timetable describes what happens from now on. Recording the moment
        # lets the scheduler leave the part of today that is already over alone, instead of
        # stamping it "missed" -- which is what importing on a Saturday used to do to the whole
        # weekend. See docs/BACKEND.md section 4.
        self.set_setting(
            "schedule_active_from", datetime.now().isoformat(timespec="seconds")
        )
        if source_path:
            self.set_setting("last_import_path", source_path)
            copy = self.archive_schedule(source_path)
            if copy:
                self.set_setting("schedule_copy_path", copy)

    def archive_schedule(self, source_path: str) -> str:
        """Keep our own copy of the imported document; return its path.

        Only ever one copy: a new import replaces the old document as completely as it replaces
        the old records.
        """
        source = Path(source_path)
        if not source.is_file():
            return ""
        directory = schedules_dir(self.path)
        destination = directory / source.name
        try:
            # Re-importing *the archived copy* is an ordinary thing to do -- it is what the
            # import dialog offers by default -- so the sweep must never delete its own source.
            current = source.resolve()
            for stale in directory.iterdir():
                if stale.is_file() and stale.resolve() != current:
                    stale.unlink()
            if current != destination.resolve():
                shutil.copy2(source, destination)
            return str(destination)
        except OSError:
            log.exception("could not archive the imported schedule")
            return ""

    # ----------------------------------------------------------------- lessons

    def _hydrate(self, rows) -> list[Lesson]:
        lessons: list[Lesson] = []
        for row in rows:
            names = [
                r["name"]
                for r in self.connection.execute(
                    "SELECT g.name FROM lesson_groups lg JOIN groups g ON g.id = lg.group_id "
                    "WHERE lg.lesson_id = ? ORDER BY g.col_lo",
                    (row["id"],),
                ).fetchall()
            ]
            lessons.append(
                Lesson(
                    id=row["id"],
                    course_id=row["course_id"],
                    day_index=row["day_index"],
                    pair=row["pair"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    subject=row["subject"],
                    teacher=row["teacher"],
                    url=row["url"],
                    provider=row["provider"],
                    needs_link=bool(row["needs_link"]),
                    is_manual=bool(row["is_manual"]),
                    source_key=row["source_key"],
                    group_names=names,
                )
            )
        return lessons

    def lessons_for_group(self, group_id: int) -> list[Lesson]:
        rows = self.connection.execute(
            "SELECT l.* FROM lessons l "
            "JOIN lesson_groups lg ON lg.lesson_id = l.id "
            "WHERE lg.group_id = ? ORDER BY l.day_index, l.pair",
            (group_id,),
        ).fetchall()
        return self._hydrate(rows)

    def lesson(self, lesson_id: int) -> Lesson | None:
        row = self.connection.execute(
            "SELECT * FROM lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
        return self._hydrate([row])[0] if row else None

    def add_lesson(self, lesson: Lesson, group_ids: list[int]) -> int:
        cursor = self.connection.execute(
            "INSERT INTO lessons(course_id, day_index, pair, start_time, end_time, subject, "
            "teacher, url, provider, needs_link, is_manual, source_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, '')",
            (
                lesson.course_id,
                lesson.day_index,
                lesson.pair,
                lesson.start_time,
                lesson.end_time,
                lesson.subject,
                lesson.teacher,
                lesson.url,
                lesson.provider,
                int(not lesson.url),
            ),
        )
        lesson_id = cursor.lastrowid
        for group_id in group_ids:
            self.connection.execute(
                "INSERT OR IGNORE INTO lesson_groups(lesson_id, group_id) VALUES (?, ?)",
                (lesson_id, group_id),
            )
        self.connection.commit()
        return lesson_id

    def update_lesson(self, lesson: Lesson, group_ids: list[int] | None = None) -> None:
        self.connection.execute(
            "UPDATE lessons SET day_index=?, pair=?, start_time=?, end_time=?, subject=?, "
            "teacher=?, url=?, provider=?, needs_link=? WHERE id=?",
            (
                lesson.day_index,
                lesson.pair,
                lesson.start_time,
                lesson.end_time,
                lesson.subject,
                lesson.teacher,
                lesson.url,
                lesson.provider,
                int(not lesson.url),
                lesson.id,
            ),
        )
        if group_ids is not None:
            self.connection.execute(
                "DELETE FROM lesson_groups WHERE lesson_id = ?", (lesson.id,)
            )
            for group_id in group_ids:
                self.connection.execute(
                    "INSERT OR IGNORE INTO lesson_groups(lesson_id, group_id) VALUES (?, ?)",
                    (lesson.id, group_id),
                )
        self.connection.commit()

    def move_lesson(
        self, lesson_id: int, day_index: int, pair: int, start_time: str, end_time: str
    ) -> None:
        """Drop a lesson into another day/slot, keeping everything else about it (drag & drop)."""
        self.connection.execute(
            "UPDATE lessons SET day_index = ?, pair = ?, start_time = ?, end_time = ? "
            "WHERE id = ?",
            (day_index, pair, start_time, end_time, lesson_id),
        )
        self.connection.commit()

    def delete_lesson(self, lesson_id: int) -> None:
        self.connection.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
        self.connection.commit()

    # ------------------------------------------------------------- occurrences

    def claim_occurrence(self, lesson_id: int, day: date, status: str) -> bool:
        """Atomically reserve today's occurrence. Returns False if it already fired.

        This is the fire-once guarantee: the caller must only open a browser when this returns
        True, and must call it *before* opening.
        """
        try:
            self.connection.execute(
                "INSERT INTO occurrences(lesson_id, occur_date, status, fired_at) "
                "VALUES (?, ?, ?, ?)",
                (lesson_id, day.isoformat(), status, datetime.now().isoformat(timespec="seconds")),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            self.connection.rollback()
            return False

    def mark_occurrence(self, lesson_id: int, day: date, status: str) -> None:
        """Force an occurrence to ``status``, creating the row if the class never fired.

        This is how the user marks a class opened or skipped by hand. It deliberately bypasses the
        claim-before-open protocol: the row is a record of a decision the user already made, and a
        ``skipped`` row is exactly what stops the scheduler opening that class later.
        """
        self.connection.execute(
            "INSERT INTO occurrences(lesson_id, occur_date, status, fired_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(lesson_id, occur_date) DO UPDATE SET "
            "status = excluded.status, fired_at = excluded.fired_at",
            (lesson_id, day.isoformat(), status, datetime.now().isoformat(timespec="seconds")),
        )
        self.connection.commit()

    def clear_occurrences(self) -> None:
        """Forget every recorded occurrence. Used when a new document replaces the timetable."""
        self.connection.execute("DELETE FROM occurrences")
        self.connection.commit()

    def clear_occurrence(self, lesson_id: int, day: date) -> None:
        """Forget a mark, so the class is eligible to open again today."""
        self.connection.execute(
            "DELETE FROM occurrences WHERE lesson_id = ? AND occur_date = ?",
            (lesson_id, day.isoformat()),
        )
        self.connection.commit()

    def set_occurrence_status(self, lesson_id: int, day: date, status: str) -> None:
        self.connection.execute(
            "UPDATE occurrences SET status = ?, fired_at = ? "
            "WHERE lesson_id = ? AND occur_date = ?",
            (status, datetime.now().isoformat(timespec="seconds"), lesson_id, day.isoformat()),
        )
        self.connection.commit()

    def occurrence(self, lesson_id: int, day: date) -> Occurrence | None:
        row = self.connection.execute(
            "SELECT * FROM occurrences WHERE lesson_id = ? AND occur_date = ?",
            (lesson_id, day.isoformat()),
        ).fetchone()
        if not row:
            return None
        return Occurrence(
            id=row["id"],
            lesson_id=row["lesson_id"],
            occur_date=row["occur_date"],
            status=row["status"],
            fired_at=row["fired_at"],
        )

    def occurrences_between(self, first: date, last: date) -> dict[tuple[int, str], Occurrence]:
        """Every occurrence in a date range, keyed by ``(lesson_id, iso date)``.

        The week grid shows a whole week at a time, so it needs one query for the range rather
        than seven for the days.
        """
        rows = self.connection.execute(
            "SELECT * FROM occurrences WHERE occur_date BETWEEN ? AND ?",
            (first.isoformat(), last.isoformat()),
        ).fetchall()
        return {
            (row["lesson_id"], row["occur_date"]): Occurrence(
                id=row["id"],
                lesson_id=row["lesson_id"],
                occur_date=row["occur_date"],
                status=row["status"],
                fired_at=row["fired_at"],
            )
            for row in rows
        }

    def occurrences_on(self, day: date) -> dict[int, Occurrence]:
        rows = self.connection.execute(
            "SELECT * FROM occurrences WHERE occur_date = ?", (day.isoformat(),)
        ).fetchall()
        return {
            row["lesson_id"]: Occurrence(
                id=row["id"],
                lesson_id=row["lesson_id"],
                occur_date=row["occur_date"],
                status=row["status"],
                fired_at=row["fired_at"],
            )
            for row in rows
        }
