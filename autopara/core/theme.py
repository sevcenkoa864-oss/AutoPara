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

# Google Sans ships with the app (``ui/fonts``): Google released it on Google Fonts under the SIL
# Open Font License, so it can be redistributed like any other open font. The Segoe entries are
# what Windows falls back to if the bundled files ever fail to load.
FONT_STACK = ("Google Sans", "Segoe UI Variable Text", "Segoe UI")

try:  # winreg exists only on Windows; keep the module importable elsewhere for tests.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


PALETTES: dict[str, dict[str, str]] = {
    # Apple's semantic colours (label / systemBackground / systemBlue ...), flattened to opaque
    # hex. Apple states most of them as translucent greys; Qt's stylesheet parser is inconsistent
    # about alpha, and a translucent label sitting on a card sitting on a tinted grid cell would
    # composite differently in each of those places. A resolved hex says the same thing everywhere.
    THEME_LIGHT: {
        "bg": "#ffffff",              # systemBackground
        "surface": "#ffffff",
        "sunken": "#f2f2f7",          # secondarySystemBackground
        "text": "#000000",            # label
        "text_muted": "#6e6e73",      # secondaryLabel
        "text_faint": "#8e8e93",      # tertiaryLabel / systemGray
        "border": "#c6c6c8",          # separator
        "border_soft": "#e5e5ea",
        "grid_line": "#efeff4",
        "accent": "#007aff",          # systemBlue -- borders, indicators, focus rings
        "accent_fill": "#0071eb",     # the prominent button: white on it clears AA, #007aff does not
        "accent_hover": "#0062cc",
        "accent_ink": "#0062cc",      # the accent used as text
        "accent_soft": "#e8f1ff",
        "accent_text": "#ffffff",
        "today_bg": "#f5f9ff",
        "now_bg": "#fff9ec",
        "card_bg": "#ffffff",
        "opened_bg": "#f2f2f7",
        "missed_bg": "#fff1f0",
        "nolink_bg": "#fff8ec",
        "skipped_bg": "#f2f2f7",
        "chip_bg": "#f2f2f7",
        "success_bg": "#e6f8ec",
        "success_fg": "#157a35",      # systemGreen darkened until label-on-fill clears AA
        "danger": "#ff3b30",          # systemRed
        "danger_bg": "#ffeceb",
        "danger_fg": "#d70015",
        "warn_bg": "#fff4e5",
        "warn_fg": "#b25000",         # systemOrange darkened for the same reason
        "zoom_bg": "#e8f1ff",
        "zoom_fg": "#0055b3",
        "meet_bg": "#e6f8ec",
        "meet_fg": "#157a35",
        "tooltip_bg": "#1c1c1e",
        "tooltip_fg": "#ffffff",
        "scroll": "#c6c6c8",
        "scroll_hover": "#aeaeb2",
        "drop_bg": "#e8f1ff",
        "drop_border": "#c6c6c8",
        "drop_hover_bg": "#e8f1ff",
        "hero_bg": "#f2f2f7",
        "banner_bg": "#fff4e5",
        "banner_border": "#ff9500",
        "banner_text": "#8a4b00",
    },
    THEME_DARK: {
        # Not pure black: a window the size of a desktop app reads as a hole punched in the screen
        # at #000000. macOS uses an elevated grey for windows and keeps black for full-screen media.
        "bg": "#1c1c1e",
        "surface": "#1c1c1e",
        "sunken": "#2c2c2e",
        "text": "#ffffff",
        "text_muted": "#98989f",
        "text_faint": "#8e8e93",
        "border": "#38383a",
        "border_soft": "#2c2c2e",
        "grid_line": "#262628",
        "accent": "#0a84ff",
        "accent_fill": "#0d6fd6",
        "accent_hover": "#0b62bd",
        "accent_ink": "#64b5ff",
        "accent_soft": "#163050",
        "accent_text": "#ffffff",
        "today_bg": "#1b2333",
        "now_bg": "#33291a",
        "card_bg": "#2c2c2e",
        "opened_bg": "#242426",
        "missed_bg": "#33211f",
        "nolink_bg": "#332a1c",
        "skipped_bg": "#242426",
        "chip_bg": "#38383a",
        "success_bg": "#1b3325",
        "success_fg": "#30d158",
        "danger": "#ff453a",
        "danger_bg": "#33211f",
        "danger_fg": "#ff6961",
        "warn_bg": "#33291a",
        "warn_fg": "#ff9f0a",
        "zoom_bg": "#163050",
        "zoom_fg": "#64b5ff",
        "meet_bg": "#1b3325",
        "meet_fg": "#30d158",
        "tooltip_bg": "#f2f2f7",
        "tooltip_fg": "#1c1c1e",
        "scroll": "#48484a",
        "scroll_hover": "#636366",
        "drop_bg": "#163050",
        "drop_border": "#48484a",
        "drop_hover_bg": "#163050",
        "hero_bg": "#2c2c2e",
        "banner_bg": "#33291a",
        "banner_border": "#ff9f0a",
        "banner_text": "#ffd08a",
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
