"""Екран першого запуску: сюди можна перетягнути файл розкладу.

До цього моменту застосунок нічого про себе не знає, тому вікно показувало один сірий рядок
тексту посеред порожнечі, а поверх нього одразу відкривався модальний діалог імпорту. Тепер
перший екран -- це те, з чим справді працюють: великий заголовок і поле, у яке кидають `.docx`.

Файл приймає ``DropWell``, а не саме вікно: поле знає обидва свої стани (запрошення і вибраний
файл) і його ж використовує діалог імпорту, тож жест «перетягнути» працює однаково в обох місцях.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import theme
from . import icons

DOCX_SUFFIX = ".docx"

# The width of the centred column. Every child is pinned to it, so the wrapped labels know what
# width to wrap at and the layout can work out the column's height from that.
COLUMN_WIDTH = 460


def wrapping(label: QLabel) -> QLabel:
    """Turn on word wrap *and* tell the layout that the height depends on the width.

    A wrapped ``QLabel`` still reports a one-line size hint unless its size policy says
    ``heightForWidth``. In a fixed-width column the layout then hands out too little height, and
    the shortfall lands on whatever cannot shrink -- here the drop well, which the button below it
    ended up overlapping by thirty pixels.
    """
    label.setWordWrap(True)
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def docx_from_mime(mime) -> str | None:
    """Шлях до першого `.docx` у перетягуваних даних, або ``None``.

    Перевіряти треба саме тут, у ``dragEnterEvent``: якщо подію не прийняти, курсор одразу
    показує «не можна», і користувач бачить відмову ще до того, як відпустить кнопку.
    """
    if mime is None or not mime.hasUrls():
        return None
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith(DOCX_SUFFIX):
            return path
    return None


class DropWell(QFrame):
    """Поле «перетягніть сюди файл». Клік по ньому рівносильний кнопці вибору файла."""

    file_dropped = Signal(str)
    clicked = Signal()

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("DropWell")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        # Fixed, not minimum: the well is the only expanding widget in its column, so a
        # minimum lets it swallow every spare pixel of a tall window.
        self.setFixedHeight(124 if compact else 180)
        self._build(compact)
        self.show_prompt()

    def _build(self, compact: bool) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        # Stretches rather than an aligned layout: aligning the layout makes every child take its
        # size hint, and a word-wrapped label's hint is narrow, so the text broke over two lines
        # in the middle of a well wide enough for four.
        layout.addStretch(1)

        self.glyph = QLabel()
        self.glyph.setAlignment(Qt.AlignCenter)
        self._glyph_size = 26 if compact else 34
        layout.addWidget(self.glyph, 0, Qt.AlignHCenter)

        # The chosen file leads and the instruction follows it: once something is picked, its
        # name is the answer to the only question this field asks.
        self.filename = QLabel()
        self.filename.setObjectName("DropWellFile")
        self.filename.setAlignment(Qt.AlignCenter)
        wrapping(self.filename)
        self.filename.hide()
        layout.addWidget(self.filename)

        self.text = QLabel()
        self.text.setObjectName("DropWellText")
        self.text.setAlignment(Qt.AlignCenter)
        wrapping(self.text)
        layout.addWidget(self.text)
        layout.addStretch(1)

        self.repaint_glyph()

    def repaint_glyph(self) -> None:
        """Значок малюється кодом, тож його колір треба оновити після зміни теми."""
        colour = theme.token("accent" if self._hovering() else "text_faint")
        self.glyph.setPixmap(icons.pixmap("document", colour, self._glyph_size))

    # ------------------------------------------------------------------ стани

    def _hovering(self) -> bool:
        return bool(self.property("hover"))

    def show_prompt(self) -> None:
        self.filename.hide()
        self.text.setText("Перетягніть сюди файл .docx")
        self.text.show()

    def show_file(self, path: str) -> None:
        """Показує ім'я файла, а не весь шлях: шлях -- це не те, що користувач тут перевіряє."""
        self.filename.setText(Path(path).name)
        self.filename.show()
        self.text.setText("Натисніть, щоб обрати інший")

    def _set_hover(self, hovering: bool) -> None:
        if self._hovering() == hovering:
            return
        self.setProperty("hover", hovering)
        self.text.setProperty("hover", hovering)
        for widget in (self, self.text):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.repaint_glyph()

    # ------------------------------------------------------------------ події

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt
        if docx_from_mime(event.mimeData()) is None:
            return
        self._set_hover(True)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt
        if docx_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt
        self._set_hover(False)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt
        self._set_hover(False)
        path = docx_from_mime(event.mimeData())
        if path is None:
            return
        event.acceptProposedAction()
        self.file_dropped.emit(path)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ImportLanding(QWidget):
    """Те, що бачить свіжовстановлений AutoPara замість сітки."""

    file_dropped = Signal(str)
    browse_requested = Signal()

    NO_SCHEDULE_TITLE = "Розклад ще не імпортовано"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._build()
        self.show_no_schedule()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 40)
        # Stretches above and below, so spare height goes around the column rather than being
        # shared out between its labels and pulling the whole thing apart.
        outer.addStretch(1)

        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        # The column takes exactly the height its children need. Without this the outer layout
        # sized it from a hint measured at the labels' *unwrapped* width, handed it fifty pixels
        # too few, and the shortfall landed on the one child that cannot shrink -- the drop well,
        # which the button below it then overlapped.
        layout.setSizeConstraint(QVBoxLayout.SetFixedSize)

        plate = QFrame()
        plate.setObjectName("HeroPlate")
        plate.setFixedSize(88, 88)
        plate_layout = QHBoxLayout(plate)
        plate_layout.setContentsMargins(0, 0, 0, 0)
        glyph = QLabel()
        glyph.setAlignment(Qt.AlignCenter)
        # Той самий значок, що й у треї та на бічній панелі: він малюється під потрібний розмір,
        # а не масштабується з готового, тож на великій плитці лишається різким.
        from .tray import icon_pixmap

        glyph.setPixmap(icon_pixmap(52))
        plate_layout.addWidget(glyph)
        layout.addWidget(plate, 0, Qt.AlignHCenter)

        self.title = QLabel(self.NO_SCHEDULE_TITLE)
        self.title.setObjectName("HeroTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setFixedWidth(COLUMN_WIDTH)
        wrapping(self.title)
        layout.addWidget(self.title)

        # Цей рядок читають тести старого порожнього стану, тому він лишається окремим віджетом.
        self.empty_label = QLabel()
        self.empty_label.setObjectName("EmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setFixedWidth(COLUMN_WIDTH)
        wrapping(self.empty_label)
        layout.addWidget(self.empty_label)

        self.well = DropWell()
        self.well.setFixedWidth(COLUMN_WIDTH)
        self.well.file_dropped.connect(self.file_dropped)
        self.well.clicked.connect(self.browse_requested)
        layout.addWidget(self.well)

        self.browse_button = QPushButton("Обрати файл…")
        self.browse_button.setObjectName("Primary")
        self.browse_button.clicked.connect(self.browse_requested)
        layout.addWidget(self.browse_button, 0, Qt.AlignHCenter)

        outer.addWidget(column, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    # ------------------------------------------------------------------ стани

    def set_state(self, title: str, message: str) -> None:
        self.title.setText(title)
        self.empty_label.setText(message)

    def show_no_schedule(self) -> None:
        self.set_state(
            self.NO_SCHEDULE_TITLE,
            "Імпортуйте файл .docx із розкладом — і AutoPara відкриватиме пари сама, "
            "за кілька хвилин до початку.",
        )

    def repaint_glyphs(self) -> None:
        self.well.repaint_glyph()

    # ------------------------------------------------------------------ події

    # Кинути файл можна будь-де на екрані, а не лише точно в поле: підсвічується все одно поле,
    # бо саме воно пояснює, що зараз станеться.
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt
        self.well.dropEvent(event)


__all__ = ["DOCX_SUFFIX", "DropWell", "ImportLanding", "docx_from_mime", "wrapping"]
