"""Light / dark colour schemes.

``ui/styles.qss`` is a template rather than a finished stylesheet: it names colours as ``$tokens``
which this module substitutes from one of two palettes. One file means a rule can never exist in
the light theme and be forgotten in the dark one.

The stored ``theme`` setting is ``system`` | ``light`` | ``dark``. ``system`` -- what a fresh
install uses -- reads Windows' own "app mode" from the registry, so AutoPara comes up matching the
desktop it was installed on.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import logging
from pathlib import Path
from string import Template

from .models import THEME_DARK, THEME_LIGHT, THEME_SYSTEM

log = logging.getLogger(__name__)

STYLESHEET = Path(__file__).resolve().parents[1] / "ui" / "styles.qss"

PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


PALETTES: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "bg": "#ffffff",
        "surface": "#ffffff",
        "sunken": "#f8f9fa",
        "text": "#202124",
        "text_muted": "#5f6368",
        "text_faint": "#80868b",
        "border": "#dadce0",
        "border_soft": "#e8eaed",
        "grid_line": "#f1f3f4",
        "accent": "#1a73e8",
        "accent_hover": "#1b66c9",
        "accent_soft": "#e8f0fe",
        "accent_text": "#ffffff",
        "today_bg": "#fafbff",
        "now_bg": "#fff8e1",
        "card_bg": "#ffffff",
        "opened_bg": "#f1f3f4",
        "missed_bg": "#fef7f6",
        "nolink_bg": "#fffdf5",
        "skipped_bg": "#f8f9fa",
        "chip_bg": "#f1f3f4",
        "success_bg": "#e6f4ea",
        "success_fg": "#137333",
        "danger": "#d93025",
        "danger_bg": "#fce8e6",
        "danger_fg": "#c5221f",
        "warn_bg": "#fef7e0",
        "warn_fg": "#b06000",
        "zoom_bg": "#e8f0fe",
        "zoom_fg": "#1a56c4",
        "meet_bg": "#e6f4ea",
        "meet_fg": "#137333",
        "tooltip_bg": "#3c4043",
        "tooltip_fg": "#ffffff",
        "scroll": "#dadce0",
        "scroll_hover": "#bdc1c6",
        "drop_bg": "#e8f0fe",
        "banner_bg": "#fef7e0",
        "banner_border": "#f2a600",
        "banner_text": "#5c3d00",
    },
    THEME_DARK: {
        "bg": "#1b1c1f",
        "surface": "#1b1c1f",
        "sunken": "#26282c",
        "text": "#e8eaed",
        "text_muted": "#9aa0a6",
        "text_faint": "#7d8288",
        "border": "#3c4043",
        "border_soft": "#2f3134",
        "grid_line": "#292b2e",
        "accent": "#8ab4f8",
        "accent_hover": "#a6c8ff",
        "accent_soft": "#22334d",
        "accent_text": "#12233d",
        "today_bg": "#202430",
        "now_bg": "#33301f",
        "card_bg": "#25272b",
        "opened_bg": "#202225",
        "missed_bg": "#33231f",
        "nolink_bg": "#2b2820",
        "skipped_bg": "#202225",
        "chip_bg": "#2f3134",
        "success_bg": "#1e3325",
        "success_fg": "#81c995",
        "danger": "#f28b82",
        "danger_bg": "#3a2321",
        "danger_fg": "#f28b82",
        "warn_bg": "#3a3020",
        "warn_fg": "#fdd663",
        "zoom_bg": "#22334d",
        "zoom_fg": "#8ab4f8",
        "meet_bg": "#1e3325",
        "meet_fg": "#81c995",
        "tooltip_bg": "#e8eaed",
        "tooltip_fg": "#202124",
        "scroll": "#3c4043",
        "scroll_hover": "#5f6368",
        "drop_bg": "#22334d",
        "banner_bg": "#33301f",
        "banner_border": "#f2a600",
        "banner_text": "#fdd663",
    },
}

# The theme currently applied to the QApplication. Widgets that paint themselves (the card shadow,
# the tray glyph) read this rather than parsing the stylesheet back out.
_active = THEME_LIGHT


def system_theme() -> str:
    """Windows' own app theme: ``AppsUseLightTheme = 0`` means the user is running dark mode."""
    if winreg is None:
        return THEME_LIGHT
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return THEME_LIGHT if value else THEME_DARK
    except (FileNotFoundError, OSError):
        return THEME_LIGHT


def resolve(theme: str) -> str:
    """Turn the stored setting (which may be ``system``) into ``light`` or ``dark``."""
    if theme == THEME_DARK:
        return THEME_DARK
    if theme == THEME_LIGHT:
        return THEME_LIGHT
    return system_theme()


def active() -> str:
    return _active


def is_dark() -> bool:
    return _active == THEME_DARK


def _asset_dir() -> Path:
    """Where generated stylesheet assets live, beside the database."""
    from .storage import default_db_path

    directory = Path(default_db_path()).parent / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def checkmark_icon(colour: str, name: str) -> str:
    """Draw a tick and return a path Qt stylesheets can reference.

    A checked QCheckBox has to *look* checked, and QSS cannot draw a shape -- ``image:`` wants a
    file. Filling the box with the accent colour was the alternative and read as a coloured
    square rather than a tick. So the tick is painted once per theme into a small PNG next to the
    database, and the stylesheet points at it.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap

    if QGuiApplication.instance() is None:
        # No GUI yet (import-time or a headless check): the stylesheet falls back to no image.
        return ""

    path = _asset_dir() / f"check-{name}.png"
    size = 15
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(
        [QPointF(3.0, 7.8), QPointF(6.2, 11.0), QPointF(12.0, 4.2)]
    )
    painter.end()
    if not pixmap.save(str(path), "PNG"):
        log.warning("could not write the checkmark asset to %s", path)
        return ""
    # QSS wants forward slashes even on Windows.
    return str(path).replace("\\", "/")


def stylesheet(theme: str) -> str:
    """Render ``styles.qss`` with the palette for ``theme`` (which may be ``system``)."""
    resolved = resolve(theme)
    try:
        template = Template(STYLESHEET.read_text(encoding="utf-8"))
    except OSError:
        log.warning("stylesheet not found at %s", STYLESHEET)
        return ""
    palette = dict(PALETTES[resolved])
    tick = checkmark_icon(palette["accent"], resolved)
    palette["check_icon"] = f'url("{tick}")' if tick else "none"
    return template.safe_substitute(palette)


def apply(app, theme: str) -> str:
    """Apply ``theme`` to a QApplication and return the resolved (``light``/``dark``) name."""
    global _active
    _active = resolve(theme)
    app.setStyleSheet(stylesheet(theme))
    return _active


def next_theme(current: str) -> str:
    """What the toolbar toggle switches to: whatever is not showing right now."""
    return THEME_LIGHT if resolve(current) == THEME_DARK else THEME_DARK


__all__ = [
    "PALETTES",
    "THEME_DARK",
    "THEME_LIGHT",
    "THEME_SYSTEM",
    "active",
    "apply",
    "is_dark",
    "next_theme",
    "resolve",
    "stylesheet",
    "system_theme",
]
