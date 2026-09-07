"""Locates the real schedule document used as the parser's regression fixture.

The document is the user's personal timetable and is deliberately *not* copied into the repository
(it contains live meeting links). Point ``AUTOPARA_TEST_DOCX`` at it, or leave it on the Desktop
where the importer found it originally.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

_ENV_VAR = "AUTOPARA_TEST_DOCX"
_FALLBACK_GLOBS = [
    str(Path.home() / "Desktop" / "*розклад*.docx"),
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
