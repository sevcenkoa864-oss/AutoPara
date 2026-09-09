"""Domain layer of the import: a docx cell grid -> courses, groups and lessons.

Implements the rules documented in docs/BACKEND.md section 2. The two that matter most:

* **R2** a group owns a *range* of logical columns, and a lesson cell belongs to every group whose
  range it overlaps -- that is how one shared session maps to several groups.
* **R5** a vertically merged lesson cell is a single block spanning several pairs.
* **R12** the same class retyped in the next slot is that same block written the long way.
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
    is_course_heading,
    is_teacher_line,
    last_pair_covered,
    normalize_text,
    pair_from_time,
    pair_slot,
    parse_time_range,
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
    # How many source cells carried a link. Merging collapses cells, so this -- not the number of
    # lessons -- is what the link oracle in tests compares against the document's <w:hyperlink>
    # count; see docs/BACKEND.md section 1.
    linked_cells: int = 0

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
            existing.linked_cells += lesson.linked_cells
            for name in lesson.group_names:
                if name not in existing.group_names:
                    existing.group_names.append(name)
    return [merged[key] for key in order]


def _compatible_text(left: str, right: str) -> bool:
    """Equal, or one side left blank -- the block then inherits the filled one (R12)."""
    first, second = normalize_text(left or ""), normalize_text(right or "")
    return not first or not second or first.casefold() == second.casefold()


def _continues(block: ParsedLesson, following: ParsedLesson) -> bool:
    """Is ``following`` the same session as ``block``, carrying on into the next slot (R12)?

    Day, groups and subject are the caller's dict key; what is left is the identity that may be
    written only once across the two cells, and the adjacency test.
    """
    if sorted(block.group_names) != sorted(following.group_names):
        return False
    if not _compatible_text(block.teacher, following.teacher):
        return False
    if block.url and following.url and block.url != following.url:
        return False
    if following.start_time < block.end_time:
        return False
    # Adjacency is a slot rule, never "this subject appears twice today": the same class can
    # legitimately run twice on one day with a gap between the sessions, and those are two lessons.
    # Comparing against the *last* pair the block covers is what lets 2->3->4 chain.
    return (
        following.pair == last_pair_covered(block.start_time, block.end_time) + 1
        or following.start_time == block.end_time
    )


def _merge_consecutive_slots(lessons: list[ParsedLesson]) -> list[ParsedLesson]:
    """R12: one class written into two adjacent slots is one session, not two.

    A double class reaches the parser either as a vMerge block (already handled while walking the
    rows) or as the cell simply retyped in the next slot. Both mean the same thing -- the class does
    not stop and nobody leaves it -- so the second slot extends the first rather than becoming a
    lesson of its own that opens a second browser tab an hour into the meeting.
    """
    kept: list[ParsedLesson] = []
    open_blocks: dict[tuple, ParsedLesson] = {}  # (day, groups, subject) -> block still open
    for lesson in lessons:
        key = (
            lesson.day_index,
            tuple(sorted(lesson.group_names)),
            normalize_text(lesson.subject).casefold(),
        )
        block = open_blocks.get(key)
        if block is not None and _continues(block, lesson):
            block.end_time = max(block.end_time, lesson.end_time)
            if not block.teacher:
                block.teacher = lesson.teacher
            if not block.url and lesson.url:
                block.url = lesson.url
                block.provider = detect_provider(lesson.url)
            block.linked_cells += lesson.linked_cells
            continue
        kept.append(lesson)
        open_blocks[key] = lesson
    return kept


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

        # R11: the Час cell may hold a bare start ("8.00") or a full range ("8.00-9.20").
        # An explicit end time in the document beats the assumed class duration.
        start_time = None
        explicit_end = None
        if time_cell is not None and not time_cell.is_empty:
            start_time, explicit_end = parse_time_range(time_cell.lines[0])
        if start_time is None or current_day is None:
            continue

        pair = None
        if pair_cell is not None and not pair_cell.is_empty:
            raw = normalize_text(pair_cell.lines[0])
            if raw.isdigit():
                pair = int(raw)
        if pair is None:  # R6: infer the pair from the start time.
            # A foreign timetable may use slots this university does not; fall back to the grid
            # row the time falls into rather than dropping the row (R10).
            pair = pair_from_time(start_time) or pair_slot(start_time)

        row_end = explicit_end or add_minutes(start_time, class_minutes)

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
                linked_cells=1 if url else 0,
            )
            lessons.append(lesson)
            if cell.vmerge == "restart":
                open_blocks[cell.column] = lesson
            else:
                open_blocks.pop(cell.column, None)

    course.lessons = _merge_consecutive_slots(_dedupe_adjacent_duplicates(lessons))
    return course


def parse_document(
    document: Document, class_minutes: int = DEFAULT_CLASS_MINUTES
) -> list[ParsedCourse]:
    """One course per table, in document order (R8).

    Courses are identified by their position in the document, never by the heading text -- the
    heading may be in any language and mixes Cyrillic and Latin numerals even in the reference
    file. The stored name is therefore always the Ukrainian ``course_label`` (R10); the heading is
    only used to note that the document looks like a timetable at all.
    """
    courses: list[ParsedCourse] = []
    ordinal = 0

    for kind, block in document.blocks:
        if kind == "p":
            continue
        if kind == "tbl":
            ordinal += 1
            courses.append(_parse_table(block, ordinal, course_label(ordinal), class_minutes))
    return courses


def looks_like_schedule(document: Document) -> bool:
    """True when the document carries at least one course heading in a supported language."""
    return any(
        kind == "p" and is_course_heading(normalize_text(str(block)))
        for kind, block in document.blocks
    )


def parse_file(path: str, class_minutes: int = DEFAULT_CLASS_MINUTES) -> list[ParsedCourse]:
    return parse_document(read_document(path), class_minutes)
