"""Іконка в системному треї, меню та сповіщення.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def build_icon() -> QIcon:
    """Невелика «календарна» іконка, намальована кодом — застосунок не тягне бінарний ресурс."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#1a73e8"))
    painter.setPen(QColor("#1a73e8"))
    painter.drawRoundedRect(6, 10, 52, 48, 10, 10)
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(QColor("#ffffff"))
    painter.drawRect(6, 22, 52, 3)
    for column in range(3):
        for row in range(2):
            painter.drawRoundedRect(15 + column * 14, 32 + row * 12, 8, 8, 2, 2)
    painter.end()
    return QIcon(pixmap)


class Tray(QObject):
    """Володіє іконкою трею. Повідомляє про намір — рішення ухвалює застосунок."""

    show_requested = Signal()
    settings_requested = Signal()
    import_requested = Signal()
    quit_requested = Signal()
    message_clicked = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(build_icon(), self)
        self.icon.setToolTip("AutoPara — автозапуск пар")
        self._build_menu()
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(self.message_clicked.emit)

    def _build_menu(self) -> None:
        menu = QMenu()
        show = QAction("Показати розклад", menu)
        show.triggered.connect(self.show_requested.emit)
        menu.addAction(show)

        import_action = QAction("Імпортувати розклад…", menu)
        import_action.triggered.connect(self.import_requested.emit)
        menu.addAction(import_action)

        settings = QAction("Налаштування…", menu)
        settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings)

        menu.addSeparator()
        quit_action = QAction("Вийти з AutoPara", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.menu = menu
        self.icon.setContextMenu(menu)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, seconds: int = 12) -> None:
        self.icon.showMessage(title, message, build_icon(), seconds * 1000)

    def set_tooltip(self, text: str) -> None:
        self.icon.setToolTip(text)
