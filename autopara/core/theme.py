"""Light / dark colour schemes.

``ui/styles.qss`` is a template rather than a finished stylesheet: it names colours as ``$tokens``
which this module substitutes from one of two palettes. One file means a rule can never exist in
the light theme and be forgotten in the dark one.

The stored ``theme`` setting is ``system`` | ``light`` | ``dark``. ``system`` -- what a fresh
install uses -- reads Windows' own "app mode" from the registry, so AutoPara comes up matching the
desktop it was installed on.
"""

from __future__ import annotations

import logging
from pathlib import Path
from string import Template

from .models import THEME_DARK, THEME_LIGHT, THEME_SYSTEM

log = logging.getLogger(__name__)

STYLESHEET = Path(__file__).resolve().parents[1] / "ui" / "styles.qss"

PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

# Google Sans ships with the app (``ui/fonts``): Google released it on Google Fonts under the SIL
# Open Font License, so it can be redistributed like any other open font. The Segoe entries are
# what Windows falls back to if the bundled files ever fail to load.
FONT_STACK = ("Google Sans", "Segoe UI Variable Text", "Segoe UI")

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


PALETTES: dict[str, dict[str, str]] = {
    # Four colours are given -- the background, the surface a class sits on, the accent, and the
    # ink -- and the rest of each palette is derived from them. Values are flattened to opaque hex
    # rather than kept translucent: Qt's stylesheet parser is inconsistent about alpha, and the
    # same translucent grey would composite differently on a card, on a tinted cell and on the rail.
    THEME_LIGHT: {
        "bg": "#ffffff",
        "surface": "#ffffff",
        "sunken": "#f5f9fa",          # the rail and every recessed group; the given surface colour
        "text": "#434958",
        "text_muted": "#6b7180",
        "text_faint": "#9aa0ad",
        "border": "#dfe3ea",
        "border_soft": "#eaeef3",
        "grid_line": "#eff2f6",
        "accent": "#6067e5",          # borders, indicators, focus rings
        "accent_fill": "#6067e5",     # the prominent button: white on it clears AA at 4.6:1
        "accent_hover": "#5158d8",
        "accent_ink": "#545bd8",      # the accent used as text, which needs the extra step
        "accent_soft": "#eceefc",
        "accent_text": "#ffffff",
        "today_bg": "#f7f8ff",
        "now_bg": "#fff9ec",
        "card_bg": "#f5f9fa",         # "bg shape para"
        "opened_bg": "#eef1f4",
        "missed_bg": "#fdf2f1",
        "nolink_bg": "#fdf8ee",
        "skipped_bg": "#eef1f4",
        "chip_bg": "#eaeef3",
        "success_bg": "#e7f5ec",
        "success_fg": "#1a7a3d",
        "danger": "#e0483c",
        "danger_bg": "#fceceb",
        "danger_fg": "#c4271c",
        "warn_bg": "#fdf3e3",
        "warn_fg": "#9a5400",
        "zoom_bg": "#eceefc",
        "zoom_fg": "#454ccc",
        "meet_bg": "#e7f5ec",
        "meet_fg": "#1a7a3d",
        "tooltip_bg": "#434958",
        "tooltip_fg": "#ffffff",
        "scroll": "#dfe3ea",
        "scroll_hover": "#c3c9d4",
        "drop_bg": "#eceefc",
        "drop_border": "#cfd5e0",
        "drop_hover_bg": "#eceefc",
        "hero_bg": "#f5f9fa",
        "banner_bg": "#fdf3e3",
        "banner_border": "#e0a33c",
        "banner_text": "#7a4a00",
    },
    THEME_DARK: {
        "bg": "#0f1319",
        "surface": "#0f1319",
        "sunken": "#131920",
        "text": "#b3bdd3",
        "text_muted": "#8791a5",
        "text_faint": "#6b7488",
        "border": "#232a35",
        "border_soft": "#1a212a",
        "grid_line": "#171e26",
        "accent": "#6067e5",
        "accent_fill": "#6067e5",
        "accent_hover": "#5158d8",
        "accent_ink": "#8f95f0",      # the accent is too dark to read *as text* on this background
        "accent_soft": "#1e2340",
        "accent_text": "#ffffff",
        "today_bg": "#141a2b",
        "now_bg": "#241f14",
        "card_bg": "#131920",         # "bg shape para"
        "opened_bg": "#11161d",
        "missed_bg": "#241618",
        "nolink_bg": "#241f14",
        "skipped_bg": "#11161d",
        "chip_bg": "#1c232d",
        "success_bg": "#132a1c",
        "success_fg": "#5fd08a",
        "danger": "#f0665c",
        "danger_bg": "#241618",
        "danger_fg": "#f08a83",
        "warn_bg": "#241f14",
        "warn_fg": "#e0a33c",
        "zoom_bg": "#1e2340",
        "zoom_fg": "#8f95f0",
        "meet_bg": "#132a1c",
        "meet_fg": "#5fd08a",
        "tooltip_bg": "#b3bdd3",
        "tooltip_fg": "#0f1319",
        "scroll": "#2a323d",
        "scroll_hover": "#3c4553",
        "drop_bg": "#1e2340",
        "drop_border": "#2e3644",
        "drop_hover_bg": "#1e2340",
        "hero_bg": "#131920",
        "banner_bg": "#241f14",
        "banner_border": "#e0a33c",
        "banner_text": "#e6bc78",
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


def token(name: str) -> str:
    """One colour of the active palette, for the widgets that paint instead of being styled."""
    return PALETTES[_active][name]


def interface_font() -> str:
    """The first family of ``FONT_STACK`` that Qt actually has.

    Resolved here rather than written into the stylesheet as a comma-separated list: Qt honours
    only the first family in such a list, so a missing Google Sans would not fall through to Segoe
    UI -- it would fall through to a default with no glyphs at all, and the whole interface would
    render as empty boxes.
    """
    try:
        from PySide6.QtGui import QFontDatabase, QGuiApplication
    except ImportError:  # pragma: no cover - Qt is a hard dependency of the app itself
        return FONT_STACK[-1]
    if QGuiApplication.instance() is None:
        return FONT_STACK[-1]
    available = set(QFontDatabase.families())
    for family in FONT_STACK:
        if family in available:
            return family
    return FONT_STACK[-1]


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


def chevron_icon(colour: str, name: str, pointing_down: bool) -> str:
    """Draw the little arrow a combo box and a spin box need.

    Same reasoning as :func:`checkmark_icon`: QSS cannot draw a shape, and styling any part of a
    sub-control makes Qt stop drawing the native one. Without this the combo boxes came up as
    empty rounded fields with nothing to say they open.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap

    if QGuiApplication.instance() is None:
        return ""

    direction = "down" if pointing_down else "up"
    path = _asset_dir() / f"chevron-{direction}-{name}.png"
    width, height = 14, 9
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    top, bottom = 3.0, 6.6
    first, last = (top, bottom) if pointing_down else (bottom, top)
    painter.drawPolyline([QPointF(3.4, first), QPointF(7.0, last), QPointF(10.6, first)])
    painter.end()
    if not pixmap.save(str(path), "PNG"):
        log.warning("could not write the chevron asset to %s", path)
        return ""
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
    palette["font_family"] = f'"{interface_font()}"'
    tick = checkmark_icon(palette["accent"], resolved)
    palette["check_icon"] = f'url("{tick}")' if tick else "none"
    for pointing_down in (True, False):
        key = "chevron_down" if pointing_down else "chevron_up"
        arrow = chevron_icon(palette["text_muted"], resolved, pointing_down)
        palette[key] = f'url("{arrow}")' if arrow else "none"
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
    "chevron_icon",
    "interface_font",
    "is_dark",
    "next_theme",
    "resolve",
    "stylesheet",
    "system_theme",
    "token",
]
