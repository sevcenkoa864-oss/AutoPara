"""Locates the real schedule document used as the parser's regression fixture.

The document is the user's personal timetable and is deliberately *not* copied into the repository
(it contains live meeting links). Point ``AUTOPARA_TEST_DOCX`` at it, or leave it on the Desktop
where the importer found it originally.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

_ENV_VAR = "AUTOPARA_TEST_DOCX"
# Searched in order. The timetable tends to migrate between the Desktop, the Downloads folder and
# wherever the messaging app dropped it, and a suite that silently skips 100+ tests because it could
# not find the file looks exactly like a passing suite -- hence the wide net and the report header.
_FALLBACK_GLOBS = [
    str(Path.home() / "Desktop" / "*розклад*.docx"),
    str(Path.home() / "Downloads" / "*розклад*.docx"),
    str(Path.home() / "Downloads" / "*" / "*розклад*.docx"),
    str(Path(os.environ.get("APPDATA", Path.home())) / "AutoPara" / "schedules" / "*.docx"),
    str(Path.home() / "Desktop" / "*.docx"),
]


def _locate() -> str | None:
    configured = os.environ.get(_ENV_VAR)
    if configured and Path(configured).is_file():
        return configured
    for pattern in _FALLBACK_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


def pytest_report_header(config) -> str:
    """Say which timetable the run used.

    Without this a missing document is invisible: every document-backed test skips and the summary
    still reads green.
    """
    path = _locate()
    if not path:
        return f"schedule document: NOT FOUND -- document-backed tests will SKIP (set {_ENV_VAR})"
    return f"schedule document: {path}"


@pytest.fixture(scope="session")
def schedule_path() -> str:
    path = _locate()
    if not path:
        pytest.skip(f"schedule .docx not found; set {_ENV_VAR} to its path")
    return path


@pytest.fixture(scope="session")
def courses(schedule_path):
    from autopara.importer.schedule_parser import parse_file

    return parse_file(schedule_path)


@pytest.fixture(scope="session")
def lessons(courses):
    return [lesson for course in courses for lesson in course.lessons]


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session.

    Qt allows a single application object per process, so every test that needs Qt -- widgets or
    bare QObject signals -- must share this one. Tests run under the offscreen platform, so no
    window is ever displayed.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def gui_app(qapp):
    """Alias kept for widget tests, so their intent reads clearly."""
    return qapp


@pytest.fixture(scope="session")
def hyperlink_targets(schedule_path) -> set[str]:
    """Every hyperlink target in the document, read straight from the zip.

    Deliberately bypasses the importer: this is the independent oracle the link tests compare
    against, so it must not share code (or bugs) with the parser under test.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(schedule_path) as archive:
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    return {
        rel.get("Target")
        for rel in rels
        if "hyperlink" in (rel.get("Type") or "") and rel.get("Target")
    }


@pytest.fixture(scope="session")
def hyperlink_element_count(schedule_path) -> int:
    """How many <w:hyperlink> elements the document contains.

    Each lesson cell carries at most one, and neither a gridSpan (shared class) nor a vMerge
    continuation duplicates it, so this equals the number of lessons that should end up with a
    link. Counting elements -- rather than unique URLs -- is what catches a link dropped from one
    lesson while the same URL survives on another.
    """
    import zipfile

    with zipfile.ZipFile(schedule_path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    return document.count("<w:hyperlink")
