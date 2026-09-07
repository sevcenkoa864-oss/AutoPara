"""Regression tests for the .docx import pipeline.

The expected numbers come from inspecting the real document and are recorded in
docs/BACKEND.md section 1. If the source document is replaced these will change; update both
places together.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import pytest

from autopara.importer.normalize import (
    TIME_TO_PAIR,
    add_minutes,
    day_index,
    dedupe,
    detect_provider,
    find_urls,
    is_course_heading,
    pair_from_time,
    pair_slot,
    pair_start_time,
    parse_time,
    parse_time_range,
)

EXPECTED_TOTAL = 77
EXPECTED_WITH_LINK = 60
EXPECTED_WITHOUT_LINK = 17
EXPECTED_PER_COURSE = [25, 11, 12, 13, 0, 16]


class TestDocumentTotals:
    def test_six_courses(self, courses):
        assert len(courses) == 6

    def test_total_lessons(self, lessons):
        assert len(lessons) == EXPECTED_TOTAL

    def test_link_split(self, lessons):
        with_link = [lesson for lesson in lessons if lesson.url]
        assert len(with_link) == EXPECTED_WITH_LINK
        assert len(lessons) - len(with_link) == EXPECTED_WITHOUT_LINK

    def test_lessons_per_course(self, courses):
        assert [len(course.lessons) for course in courses] == EXPECTED_PER_COURSE

    def test_course_v_is_empty(self, courses):
        """Course V genuinely has no classes; that is a valid state, not a failure."""
        assert courses[4].lessons == []
        assert [group.name for group in courses[4].groups] == ["51 група"]

    def test_every_lesson_is_well_formed(self, lessons):
        for lesson in lessons:
            assert lesson.subject, "subject is required"
            assert 0 <= lesson.day_index <= 6
            assert 1 <= lesson.pair <= 6
            assert lesson.start_time < lesson.end_time
            assert lesson.group_names, "a lesson must belong to at least one group"

    def test_providers_are_classified(self, lessons):
        providers = {lesson.provider for lesson in lessons}
        assert providers <= {"zoom", "google_meet", "unknown"}
        linked = [lesson for lesson in lessons if lesson.url]
        assert all(lesson.provider != "unknown" for lesson in linked)


class TestMergeHandling:
    """The rules that the original spec got wrong -- see docs/BACKEND.md R1, R2, R5."""

    def test_spanning_group_header_maps_to_a_column_range(self, courses):
        """Course IV's grid has 7 columns but only 2 groups; the second header spans 3 (R2)."""
        course_iv = courses[3]
        ranges = [(group.name, group.col_lo, group.col_hi) for group in course_iv.groups]
        assert ranges == [("41 група", 3, 3), ("42 група", 4, 6)]

    def test_shared_class_is_one_lesson_with_many_groups(self, courses):
        """A gridSpan=2 cell is a single session shared by both groups, not two lessons (R1/R2)."""
        course_i = courses[0]
        monday_first = [
            lesson
            for lesson in course_i.lessons
            if lesson.day_index == 0 and lesson.pair == 1
        ]
        assert len(monday_first) == 1
        lesson = monday_first[0]
        assert lesson.subject == "Історія України"
        assert lesson.group_names == ["А2-Бд26-11 група", "А2-Бд26-12 група"]
        assert lesson.provider == "google_meet"

    def test_shared_lessons_are_never_duplicated(self, lessons):
        """No two lessons may share (day, pair, subject) within the same group."""
        seen = set()
        for lesson in lessons:
            for group in lesson.group_names:
                key = (group, lesson.day_index, lesson.pair, lesson.subject)
                assert key not in seen, f"duplicate lesson for {key}"
                seen.add(key)

    def test_vertically_merged_block_spans_several_pairs(self, courses):
        """The elective block is one lesson covering consecutive pairs, not one per pair (R5)."""
        blocks = [
            lesson
            for course in courses
            for lesson in course.lessons
            if "вільного вибору" in lesson.subject
        ]
        assert len(blocks) == 3
        for block in blocks:
            assert block.start_time == "08:00"
            # A single 80-minute pair would end at 09:20; these extend well past that.
            assert block.end_time > "09:20"
            assert not block.url, "the elective block has no link"


class TestLinkExtraction:
    def test_links_are_not_duplicated(self, lessons):
        """Each URL is stored once even though the document holds it as both a relationship
        and visible text (R3)."""
        for lesson in lessons:
            if lesson.url:
                assert lesson.url.count("http") == 1

    def test_url_absent_lessons_are_flagged(self, lessons):
        without = [lesson for lesson in lessons if not lesson.url]
        assert len(without) == EXPECTED_WITHOUT_LINK
        assert all(lesson.needs_link for lesson in without)
        assert all(lesson.provider == "unknown" for lesson in without)

    def test_subject_text_excludes_the_url(self, lessons):
        for lesson in lessons:
            assert "http" not in lesson.subject
            assert "http" not in lesson.teacher


class TestDayAndPairInference:
    def test_all_six_weekdays_present(self, lessons):
        """Days are carried down from vMerge 'restart' rows (R4); Sunday is never used."""
        days = {lesson.day_index for lesson in lessons}
        assert days == {0, 1, 2, 3, 4, 5}

    def test_friday_uses_a_backtick_apostrophe(self):
        """The document writes П`ятниця with U+0060 (R8)."""
        assert day_index("П`ятниця") == 4
        assert day_index("П'ятниця") == 4

    def test_pair_matches_start_time(self, lessons):
        """Пара is blank on one row and is inferred from Час (R6)."""
        for lesson in lessons:
            hour, minute = lesson.start_time.split(":")
            assert TIME_TO_PAIR[f"{int(hour)}.{minute}"] == lesson.pair


class TestNormalizeHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [("8.00", "08:00"), ("16.10", "16:10"), ("9:30", "09:30"), ("nope", None)],
    )
    def test_parse_time(self, raw, expected):
        assert parse_time(raw) == expected

    def test_pair_from_time(self):
        assert pair_from_time("11.20") == 3
        assert pair_from_time("07.00") is None

    def test_add_minutes_clamps_at_midnight(self):
        assert add_minutes("08:00", 80) == "09:20"
        assert add_minutes("23:30", 120) == "23:59"

    def test_detect_provider(self):
        assert detect_provider("https://us02web.zoom.us/j/1") == "zoom"
        assert detect_provider("https://meet.google.com/a-b-c") == "google_meet"
        assert detect_provider("https://example.com") == "unknown"
        assert detect_provider(None) == "unknown"

    def test_find_urls_strips_trailing_punctuation(self):
        assert find_urls("see https://meet.google.com/a-b-c.") == ["https://meet.google.com/a-b-c"]

    def test_dedupe_preserves_order(self):
        assert dedupe(["b", "a", "b", ""]) == ["b", "a"]


class TestAnyLanguageDocuments:
    """R10: the importer reads any language and writes Ukrainian."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Понеділок", 0), ("Monday", 0), ("Mon", 0), ("Poniedziałek", 0), ("Montag", 0),
            ("вторник", 1), ("Tuesday", 1), ("wtorek", 1),
            ("Wednesday", 2), ("środa", 2), ("sroda", 2), ("среда", 2),
            ("Четвер", 3), ("Thursday", 3), ("czwartek", 3),
            ("П'ятниця", 4), ("Friday", 4), ("piątek", 4),
            ("Субота", 5), ("Saturday", 5), ("sobota", 5),
            ("Неділя", 6), ("Sunday", 6), ("niedziela", 6),
        ],
    )
    def test_day_names_in_several_languages(self, raw, expected):
        assert day_index(raw) == expected

    def test_a_dated_day_cell_still_resolves(self):
        assert day_index("Понеділок 02.09") == 0
        assert day_index("Monday, 2 March") == 0

    def test_unknown_text_is_not_a_day(self):
        assert day_index("Історія України") is None
        assert day_index("") is None

    def test_course_headings_are_recognised_in_several_languages(self):
        assert is_course_heading("І КУРС")
        assert is_course_heading("YEAR 1")
        assert is_course_heading("Rok II")
        assert not is_course_heading("он-лайн")

    def test_course_names_are_always_ukrainian(self, courses):
        """Whatever the document's heading said, the stored label is Ukrainian."""
        assert [course.name for course in courses] == [
            "I курс", "II курс", "III курс", "IV курс", "V курс", "VI курс"
        ]


class TestTimeCells:
    def test_a_range_yields_both_ends(self):
        assert parse_time_range("8.00-9.20") == ("08:00", "09:20")
        assert parse_time_range("8:00 – 9:20") == ("08:00", "09:20")

    def test_a_bare_start_has_no_end(self):
        assert parse_time_range("8.00") == ("08:00", None)

    def test_nonsense_yields_nothing(self):
        assert parse_time_range("немає") == (None, None)

    def test_a_backwards_range_is_ignored(self):
        assert parse_time_range("9.20-8.00") == ("09:20", None)

    def test_pair_slot_places_any_time_in_the_grid(self):
        assert pair_slot("08:00") == 1      # an exact slot
        assert pair_slot("07:15") == 1      # before the first slot
        assert pair_slot("12:00") == 3      # between slots -- the one already running
        assert pair_slot("23:00") == 10     # the grid runs to the end of the evening

    def test_the_grid_covers_the_whole_teaching_day(self):
        """A class can be created at any time from 08:00 to 23:00, not only in the six slots."""
        starts = [pair_start_time(pair) for pair in sorted(TIME_TO_PAIR.values())]
        assert starts[0] == "08:00"
        assert add_minutes(starts[-1], 80) >= "23:00"
        # The university's own six slots are untouched -- the parser still depends on them.
        assert starts[:6] == ["08:00", "09:30", "11:20", "13:00", "14:40", "16:10"]
