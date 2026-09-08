"""Головне вікно: панель інструментів, банер пропущеної пари, тижнева сітка та рядок стану.

Режиму редагування немає: сітка редагована завжди. Лівий клік по парі підключає до неї, права
кнопка відкриває меню дій, клік по порожній клітинці пропонує створити пару, перетягування
переносить пару в інший день або слот.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import theme
from ..core.models import (
    STATUS_MISSED,
    STATUS_OPENED,
    STATUS_SKIPPED,
    Lesson,
)
from ..core.scheduler import Scheduler
from ..core.storage import Storage
from ..importer.normalize import (
    DAY_NAMES,
    add_minutes,
    minutes_between,
    pair_slot,
    week_start,
)
from . import icons
from .catchup_banner import CatchupBanner
from .edit_dialog import EditDialog
from .import_landing import ImportLanding
from .settings_dialog import SettingsDialog
from .setup_dialog import SetupDialog
from .tray import icon_pixmap
from .week_grid import WeekGrid


# A rail, not a panel: with no text on it, its width is the width of one button plus air.
SIDEBAR_WIDTH = 72


class MainWindow(QMainWindow):
    """Постійно редагована сітка тижня з навігацією по тижнях."""

    closed_to_tray = Signal()

    def __init__(self, storage: Storage, scheduler: Scheduler):
        super().__init__()
        self.storage = storage
        self.scheduler = scheduler
        self.setWindowTitle("AutoPara — автозапуск пар")
        # Wide enough that the sidebar does not cost the grid a day column.
        self.resize(1240, 800)
        self._build()

        self.scheduler.lesson_opened.connect(self._lesson_opened)
        self.scheduler.lesson_missed.connect(lambda _: self.reload())

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        central = QWidget()
        columns = QHBoxLayout(central)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        columns.addWidget(self._build_sidebar())

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = CatchupBanner()
        self.banner.connect_requested.connect(self._catchup_connect)
        self.banner.dismissed.connect(self._catchup_dismiss)
        layout.addWidget(self.banner)

        self.grid = WeekGrid()
        self.grid.lesson_clicked.connect(self._lesson_clicked)
        self.grid.lesson_menu_requested.connect(self._lesson_menu_requested)
        self.grid.slot_clicked.connect(self._slot_clicked)
        self.grid.lesson_dropped.connect(self._lesson_dropped)
        layout.addWidget(self.grid, 1)

        self.landing = ImportLanding()
        self.landing.file_dropped.connect(lambda path: self.open_import(path))
        self.landing.browse_requested.connect(self.open_import)
        self.landing.hide()
        layout.addWidget(self.landing, 1)
        # Решта вікна зверталася просто до порожнього напису; він і далі тут, усередині екрана
        # імпорту, тож ніщо навколо не мусить знати, що він переїхав.
        self.empty_label = self.landing.empty_label

        columns.addWidget(content, 1)
        self.setCentralWidget(central)
        # Після бічної панелі та екрана імпорту: значки малюються в кольорі теми, для обох одразу.
        self._refresh_icons()

    def _build_sidebar(self) -> QWidget:
        """Дії живуть у вузькій колонці ліворуч, а не в смузі згори.

        Сітка тижня -- широка й невисока, тож горизонтальна панель забирала саме ту висоту, якої
        календарю бракує. У колонці немає жодного слова: сам застосунок не мусить називати себе у
        власному вікні, а що робить кожна кнопка -- каже підказка під курсором.
        """
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(SIDEBAR_WIDTH)
        column = QVBoxLayout(bar)
        column.setContentsMargins(0, 18, 0, 18)
        column.setSpacing(12)

        # Значок замість слова «AutoPara». Обраний курс і група більше не написані на панелі --
        # вони не змінюються тижнями, а місце займали постійно; тепер це підказка на значку.
        self.brand = QLabel()
        self.brand.setObjectName("Brand")
        self.brand.setPixmap(icon_pixmap(30))
        self.brand.setAlignment(Qt.AlignCenter)
        column.addWidget(self.brand, 0, Qt.AlignHCenter)

        column.addStretch(1)

        self.add_button = self._icon_button("Додати пару", lambda: self._edit_lesson(None))
        self.add_button.setObjectName("PrimaryRound")
        self.add_button.setFixedSize(40, 40)
        column.addWidget(self.add_button, 0, Qt.AlignHCenter)

        # Три значки стоять щільно, щоб читалися однією групою дрібних дій, а не трьома
        # знаками, що розбрелися під кнопкою над ними.
        cluster = QVBoxLayout()
        cluster.setSpacing(2)
        self.import_button = self._icon_button("Імпортувати розклад…", self.open_import)
        cluster.addWidget(self.import_button, 0, Qt.AlignHCenter)

        self.settings_button = self._icon_button("Налаштування", self.open_settings)
        cluster.addWidget(self.settings_button, 0, Qt.AlignHCenter)

        self.theme_button = self._icon_button("", self.toggle_theme)
        cluster.addWidget(self.theme_button, 0, Qt.AlignHCenter)
        column.addLayout(cluster)

        return bar

    def _icon_button(self, tooltip: str, handler) -> QPushButton:
        """Кнопка-значок 36x36 -- зручна для миші й не перетворює панель на суцільні кнопки.

        Текст лишається порожнім назавжди: значок ставить ``_refresh_icons`` після кожної зміни
        теми, бо значки малюються кодом і мають перефарбовуватися разом із нею.
        """
        button = QPushButton("")
        button.setObjectName("IconButton")
        button.setFixedSize(36, 36)
        button.setIconSize(QSize(20, 20))
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        return button

    # ------------------------------------------------------------------- week

    def monday(self) -> date:
        """Понеділок поточного тижня — сітка завжди показує саме його."""
        return week_start(date.today())

    def date_of(self, lesson: Lesson) -> date:
        """Календарна дата цієї пари цього тижня — до неї прив'язуються позначки."""
        return self.monday() + timedelta(days=lesson.day_index)

    # ----------------------------------------------------------------- render

    def current_lessons(self) -> list[Lesson]:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            return []
        return self.storage.lessons_for_group(settings.selected_group_id)

    def week_statuses(self, lessons: list[Lesson]) -> dict[int, str]:
        """Стан кожної пари цього тижня (пара трапляється в тижні один раз)."""
        monday = self.monday()
        occurrences = self.storage.occurrences_between(monday, monday + timedelta(days=6))
        statuses: dict[int, str] = {}
        for lesson in lessons:
            key = (lesson.id, self.date_of(lesson).isoformat())
            occurrence = occurrences.get(key)
            if occurrence is not None:
                statuses[lesson.id] = occurrence.status
        return statuses

    def reload(self) -> None:
        settings = self.storage.settings()
        lessons = self.current_lessons()
        group = (
            self.storage.group(settings.selected_group_id)
            if settings.selected_group_id
            else None
        )

        if group is None:
            self.grid.hide()
            self.landing.show_no_schedule()
            self.landing.show()
            self.brand.setToolTip("Розклад ще не імпортовано")
        elif not lessons:
            self.grid.hide()
            self.landing.set_state(
                "Тут поки порожньо",
                f"У групі {group.name} немає пар в імпортованому розкладі. "
                "Натисніть «Додати пару» або імпортуйте інший файл.",
            )
            self.landing.show()
            self._set_subtitle(group)
        else:
            self.landing.hide()
            self.grid.show()
            statuses = self.week_statuses(lessons)
            self.grid.render_week(
                lessons,
                statuses=statuses,
                next_lesson_id=self._next_lesson_id(lessons, statuses),
                today=date.today(),
            )
            self._set_subtitle(group)

    def _set_subtitle(self, group) -> None:
        """Курс, група і час відкриття -- підказка на значку, а не напис на панелі.

        Ці чотири рядки не змінюються тижнями, але місце на екрані займали постійно. Підказка
        показує їх тоді, коли про них справді питають.
        """
        settings = self.storage.settings()
        course = self.storage.course(group.course_id)
        parts = [group.name]
        if group.specialty:
            parts.append(group.specialty)
        if course:
            parts.insert(0, course.name)
        parts.append(f"відкриття за {settings.lead_minutes} хв")
        self.brand.setToolTip("\n".join(parts))

    def _next_lesson_id(self, lessons: list[Lesson], statuses: dict[int, str]) -> int | None:
        now = datetime.now()
        today = now.date()
        upcoming = [
            lesson
            for lesson in lessons
            if lesson.day_index == today.weekday()
            and lesson.ends_on(today) > now
            and lesson.id not in statuses
        ]
        if not upcoming:
            return None
        return min(upcoming, key=lambda lesson: lesson.start_time).id

    # ------------------------------------------------------------------ theme

    def _refresh_icons(self) -> None:
        """Перемальовує значки в кольорі активної теми. Підписів на цих кнопках немає."""
        dark = theme.is_dark()
        ink = theme.token("text")
        self.add_button.setIcon(icons.icon("add", theme.token("accent_text"), 22))
        self.import_button.setIcon(icons.icon("import", ink, 20))
        self.settings_button.setIcon(icons.icon("settings", ink, 20))
        self.theme_button.setIcon(icons.icon("sun" if dark else "moon", ink, 20))
        self.theme_button.setToolTip(
            "Перемкнути на світлу тему" if dark else "Перемкнути на темну тему"
        )
        self.landing.repaint_glyphs()
        self.banner.repaint_glyph()

    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, self.storage.settings().theme)
        self._refresh_icons()
        self.reload()

    def toggle_theme(self) -> None:
        """Явно закріплює світлу або темну тему замість «як у системі»."""
        wanted = theme.next_theme(self.storage.settings().theme)
        self.storage.set_setting("theme", wanted)
        self.apply_theme()

    # ------------------------------------------------------- catch-up (банер)

    def offer_catchup(self, lesson_id: int) -> None:
        lesson = self.storage.lesson(lesson_id)
        if lesson is not None:
            self.banner.offer(lesson)

    def _catchup_connect(self, lesson_id: int) -> None:
        # A successful open reloads through ``lesson_opened``; reloading again here would rebuild
        # the whole grid a second time while the browser is starting.
        if not self.scheduler.open_now(lesson_id):
            QMessageBox.warning(
                self, "Не вдалося відкрити", "Посилання не вдалося відкрити у браузері."
            )
            self.reload()

    def _catchup_dismiss(self, lesson_id: int) -> None:
        """«Закрити» -- пара лишається пропущеною й більше не питає про себе сьогодні."""
        self.scheduler.mark(lesson_id, STATUS_MISSED)
        self.reload()

    def _lesson_opened(self, lesson_id: int) -> None:
        self.banner.resolve(lesson_id)
        self.reload()

    # ---------------------------------------------------------------- actions

    def _lesson_clicked(self, lesson_id: int) -> None:
        """Лівий клік — підключитися до пари.

        Це те, заради чого програму відкривають, тож воно коштує один клік, а не клік плюс вибір
        у меню. Решта дій — на правій кнопці.
        """
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        if not lesson.url:
            # Відкривати нічого: показуємо меню, де перший пункт — додати посилання.
            self._show_lesson_menu(lesson)
            return

        day = self.date_of(lesson)
        # ``lesson_opened`` перезавантажує сітку сам, тож тут другого перемальовування немає.
        if not self.scheduler.open_now(lesson.id, day):
            QMessageBox.warning(
                self, "Не вдалося відкрити", "Посилання не вдалося відкрити у браузері."
            )

    def _lesson_menu_requested(self, lesson_id: int) -> None:
        """Права кнопка — повне меню дій для пари."""
        lesson = self.storage.lesson(lesson_id)
        if lesson is not None:
            self._show_lesson_menu(lesson)

    def _show_lesson_menu(self, lesson: Lesson) -> None:
        """Одне меню дій для пари: відкрити / редагувати / позначити / видалити."""
        day = self.date_of(lesson)
        occurrence = self.storage.occurrence(lesson.id, day)

        menu = QMenu(self)
        if lesson.url:
            open_action = menu.addAction("Відкрити посилання")
            add_link_action = None
        else:
            open_action = None
            add_link_action = menu.addAction("Додати посилання…")
        edit_action = menu.addAction("Редагувати…")

        menu.addSeparator()
        mark_opened_action = menu.addAction("Позначити як відкриту")
        mark_skipped_action = menu.addAction("Позначити як пропущену")
        clear_action = menu.addAction("Зняти позначку") if occurrence else None

        menu.addSeparator()
        delete_action = menu.addAction("Видалити пару")

        chosen = menu.exec(self.cursor().pos())
        if chosen is None:
            return
        if chosen is open_action:
            # ``lesson_opened`` already reloads on success, so this branch returns rather than
            # rebuilding the grid a second time behind the opening browser.
            if self.scheduler.open_now(lesson.id, day):
                return
            QMessageBox.warning(
                self, "Не вдалося відкрити", "Посилання не вдалося відкрити у браузері."
            )
        elif chosen is add_link_action or chosen is edit_action:
            self._edit_lesson(lesson)
        elif chosen is mark_opened_action:
            self.scheduler.mark(lesson.id, STATUS_OPENED, day)
        elif chosen is mark_skipped_action:
            self.scheduler.mark(lesson.id, STATUS_SKIPPED, day)
        elif clear_action is not None and chosen is clear_action:
            self.scheduler.clear_mark(lesson.id, day)
        elif chosen is delete_action:
            self._delete_lesson(lesson)
        self.reload()

    def _delete_lesson(self, lesson: Lesson) -> None:
        confirm = QMessageBox.question(
            self,
            "Видалити пару",
            f"Видалити «{lesson.subject}» з розкладу?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.storage.delete_lesson(lesson.id)

    def _slot_clicked(self, day_index: int, start: str) -> None:
        """Клік по вільній годині — як у Google Calendar: спливна пропозиція створити пару."""
        settings = self.storage.settings()
        if not settings.selected_group_id:
            QMessageBox.information(
                self, "Спершу імпорт", "Імпортуйте розклад, перш ніж додавати пари."
            )
            return
        menu = QMenu(self)
        create = menu.addAction(f"➕ Створити пару · {DAY_NAMES[day_index]}, {start}")
        menu.addSeparator()
        menu.addAction("Скасувати")
        if menu.exec(self.cursor().pos()) is create:
            self._edit_lesson(None, day_index=day_index, start_time=start)

    def _lesson_dropped(self, lesson_id: int, day_index: int, start: str) -> None:
        """Перетягування переносить пару на іншу годину, зберігаючи її тривалість."""
        lesson = self.storage.lesson(lesson_id)
        if lesson is None:
            return
        if lesson.day_index == day_index and lesson.start_time == start:
            return
        duration = minutes_between(lesson.start_time, lesson.end_time) or (
            self.storage.settings().class_duration_minutes
        )
        self.storage.move_lesson(
            lesson.id, day_index, pair_slot(start), start, add_minutes(start, duration)
        )
        self.reload()

    def _edit_lesson(
        self, lesson: Lesson | None, day_index: int | None = None, start_time: str | None = None
    ) -> None:
        settings = self.storage.settings()
        if not settings.selected_group_id:
            QMessageBox.information(
                self, "Спершу імпорт", "Імпортуйте розклад, перш ніж додавати пари."
            )
            return
        dialog = EditDialog(
            self.storage,
            settings.selected_group_id,
            lesson,
            self,
            day_index=day_index,
            start_time=start_time,
        )
        if dialog.exec():
            self.reload()

    def open_import(self, path: str | None = None) -> None:
        """``path`` -- файл, який щойно кинули на екран імпорту; діалог одразу його читає."""
        dialog = SetupDialog(self.storage, self, path=path)
        if dialog.exec():
            self.reload()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.storage, self)
        if dialog.exec():
            # Тема могла змінитися; apply_theme сам перемальовує сітку.
            self.apply_theme()

    # ----------------------------------------------------------------- window

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        """Закриття вікна ховає його в трей; вихід — лише через «Вийти» у треї."""
        event.ignore()
        self.hide()
        self.closed_to_tray.emit()
