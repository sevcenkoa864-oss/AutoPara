"""Domain layer of the import: a docx cell grid -> courses, groups and lessons.

Implements the rules documented in docs/BACKEND.md section 2. The two that matter most:

* **R2** a group owns a *range* of logical columns, and a lesson cell belongs to every group whose
  range it overlaps -- that is how one shared session maps to several groups.
* **R5** a vertically merged lesson cell is a single block spanning several pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .docx_reader import Cell, Document, Table, read_document
from .normalize import (
    DEFAULT_CLASS_MINUTES,
    add_minutes,
    course_label,
    day_index,
    dedupe,
    detect_provider,
    find_urls,
    is_teacher_line,
    normalize_text,
    pair_from_time,
    parse_time,
)

# Columns 0..2 are День / Пара / Час; group columns start at 3.
FIRST_GROUP_COLUMN = 3
HEADER_ROWS = 2


@dataclass
class ParsedGroup:
    name: str
    specialty: str
    col_lo: int
    col_hi: int


@dataclass
class ParsedLesson:
    day_index: int
    pair: int
    start_time: str
    end_time: str
    subject: str
    teacher: str
    url: str | None
    provider: str
    group_names: list[str]

    @property
    def needs_link(self) -> bool:
        return not self.url

    def source_key(self, course_ordinal: int) -> str:
        """Stable identity across re-imports (BACKEND.md 'Re-import behavior')."""
        subject = normalize_text(self.subject).casefold()
        return f"{course_ordinal}|{self.day_index}|{self.pair}|{subject}"


@dataclass
class ParsedCourse:
    ordinal: int
    name: str
    groups: list[ParsedGroup] = field(default_factory=list)
    lessons: list[ParsedLesson] = field(default_factory=list)


def _header_groups(table: Table) -> list[ParsedGroup]:
    """Build group column ranges from the two header rows (R2).

    A header cell may itself span several grid columns -- in the ІV КУРС table the grid has 7
    columns but only 2 groups, because the second group header spans 3.
    """
    if len(table.rows) < HEADER_ROWS:
        return []

    groups: list[ParsedGroup] = []
    for cell in table.rows[0].cells:
        if cell.column < FIRST_GROUP_COLUMN or cell.is_empty:
            continue
        name = normalize_text(" ".join(cell.lines))
        groups.append(
            ParsedGroup(name=name, specialty="", col_lo=cell.column, col_hi=cell.last_column)
        )

    # Row 1 repeats the specialty under each group column.
    for group in groups:
        cell = table.rows[1].at(group.col_lo)
        if cell is not None and not cell.is_empty:
            group.specialty = normalize_text(" ".join(cell.lines))
    return groups


def _cell_content(cell: Cell) -> tuple[str, str, str | None]:
    """Split a lesson cell into (subject, teacher, url) per R9, deduping the doubled link (R3)."""
    urls = list(cell.links)
    text_lines: list[str] = []
    for line in cell.lines:
        found = find_urls(line)
        if found:
            urls.extend(found)
            # Keep any prose that surrounded the URL, drop the URL itself from display text.
            remainder = line
            for url in found:
                remainder = remainder.replace(url, " ")
            remainder = normalize_text(remainder)
            if remainder:
                text_lines.append(remainder)
        else:
            text_lines.append(normalize_text(line))

    text_lines = [line for line in text_lines if line]
    subject = ""
    teacher = ""
    for line in text_lines:
        if is_teacher_line(line):
            if not teacher:
                teacher = line
        elif not subject:
            subject = line
    if not subject and text_lines:
        subject = text_lines[0]

    unique = dedupe([url for url in urls if url])
    return subject, teacher, (unique[0] if unique else None)


def _groups_for(cell: Cell, groups: list[ParsedGroup]) -> list[str]:
    """Every group whose column range overlaps the cell -- the shared-class rule (R2)."""
    return [group.name for group in groups if cell.overlaps(group.col_lo, group.col_hi)]


def _dedupe_adjacent_duplicates(lessons: list[ParsedLesson]) -> list[ParsedLesson]:
    """Defensive fallback for documents where merges were flattened into repeated text.

    This document stores shared classes as genuine gridSpan merges, so this normally does nothing.
    It protects against .docx files produced by other tooling, where the same class is duplicated
    across adjacent group columns instead (BACKEND.md R2).
    """
    merged: dict[tuple, ParsedLesson] = {}
    order: list[tuple] = []
    for lesson in lessons:
        key = (
            lesson.day_index,
            lesson.pair,
            normalize_text(lesson.subject).casefold(),
            normalize_text(lesson.teacher).casefold(),
            lesson.url or "",
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = lesson
            order.append(key)
        else:
            for name in lesson.group_names:
                if name not in existing.group_names:
                    existing.group_names.append(name)
    return [merged[key] for key in order]


def _parse_table(table: Table, ordinal: int, name: str, class_minutes: int) -> ParsedCourse:
    course = ParsedCourse(ordinal=ordinal, name=name)
    course.groups = _header_groups(table)
    if not course.groups:
        return course

    current_day: int | None = None
    open_blocks: dict[int, ParsedLesson] = {}  # column -> block started above (R5)
    lessons: list[ParsedLesson] = []

    for row in table.rows[HEADER_ROWS:]:
        day_cell = row.at(0)
        pair_cell = row.at(1)
        time_cell = row.at(2)

        # R4: the day is only present on the vMerge 'restart' row; carry it forward.
        if day_cell is not None and not day_cell.is_empty:
            resolved = day_index(day_cell.lines[0])
            if resolved is not None:
                current_day = resolved

        start_time = None
        if time_cell is not None and not time_cell.is_empty:
            start_time = parse_time(time_cell.lines[0])
        if start_time is None or current_day is None:
            continue

        pair = None
        if pair_cell is not None and not pair_cell.is_empty:
            raw = normalize_text(pair_cell.lines[0])
            if raw.isdigit():
                pair = int(raw)
        if pair is None:  # R6: infer the pair from the start time.
            pair = pair_from_time(start_time)
        if pair is None:
            continue

        row_end = add_minutes(start_time, class_minutes)

        for cell in row.cells:
            if cell.column < FIRST_GROUP_COLUMN:
                continue

            if cell.vmerge == "continue":
                # R5: extend the block that started above so it covers this pair too.
                block = open_blocks.get(cell.column)
                if block is not None:
                    block.end_time = row_end
                continue

            if cell.is_empty:
                open_blocks.pop(cell.column, None)
                continue

            subject, teacher, url = _cell_content(cell)
            if not subject:
                open_blocks.pop(cell.column, None)
                continue

            lesson = ParsedLesson(
                day_index=current_day,
                pair=pair,
                start_time=start_time,
                end_time=row_end,
                subject=subject,
                teacher=teacher,
                url=url,
                provider=detect_provider(url),
                group_names=_groups_for(cell, course.groups),
            )
            lessons.append(lesson)
            if cell.vmerge == "restart":
                open_blocks[cell.column] = lesson
            else:
                open_blocks.pop(cell.column, None)

    course.lessons = _dedupe_adjacent_duplicates(lessons)
    return course


def parse_document(
    document: Document, class_minutes: int = DEFAULT_CLASS_MINUTES
) -> list[ParsedCourse]:
    """Pair each КУРС heading with the table that follows it, in document order (R8)."""
    courses: list[ParsedCourse] = []
    pending_heading: str | None = None
    ordinal = 0

    for kind, block in document.blocks:
        if kind == "p":
            text = normalize_text(str(block))
            if "КУРС" in text.upper():
                pending_heading = text
        elif kind == "tbl":
            ordinal += 1
            name = pending_heading or course_label(ordinal)
            pending_heading = None
            courses.append(_parse_table(block, ordinal, name, class_minutes))
    return courses


def parse_file(path: str, class_minutes: int = DEFAULT_CLASS_MINUTES) -> list[ParsedCourse]:
    return parse_document(read_document(path), class_minutes)
