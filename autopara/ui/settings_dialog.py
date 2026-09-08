"""Налаштування: сповіщення, поведінка з пропущеними парами, тема, автозапуск."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core import autostart
from ..core.models import (
    CATCHUP_MISSED,
    CATCHUP_NOTIFY,
    CATCHUP_OPEN,
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
)
from ..core.storage import Storage

# Порядок відповідає вимозі: спершу «сповістити й відкрити з підтвердженням» -- це і є типова
# поведінка, яка не дає застосунку самому відкривати вікна після пропущеної пари.
CATCHUP_CHOICES = [
    (CATCHUP_NOTIFY, "Сповістити мене й відкрити після підтвердження"),
    (CATCHUP_OPEN, "Відкрити одразу"),
    (CATCHUP_MISSED, "Позначити як пропущену"),
]

THEME_CHOICES = [
    (THEME_SYSTEM, "Як у системі"),
    (THEME_LIGHT, "Світла"),
    (THEME_DARK, "Темна"),
]


class SettingsDialog(QDialog):
    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("Налаштування")
        self.setMinimumWidth(470)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Налаштування")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(11)

        self.lead_spin = QSpinBox()
        self.lead_spin.setRange(0, 120)
        self.lead_spin.setSuffix(" хв до початку")
        form.addRow("Відкривати посилання", self.lead_spin)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(10, 240)
        self.duration_spin.setSuffix(" хв")
        form.addRow("Тривалість пари", self.duration_spin)

        self.theme_combo = QComboBox()
        for value, label in THEME_CHOICES:
            self.theme_combo.addItem(label, value)
        form.addRow("Тема", self.theme_combo)

        layout.addLayout(form)

        # ------------------------------------------------------------ сповіщення
        notify_label = QLabel("Сповіщення")
        notify_label.setObjectName("SectionLabel")
        layout.addWidget(notify_label)

        self.notify_check = QCheckBox("Нагадувати про пару перед початком")
        self.notify_check.toggled.connect(self._notify_toggled)
        layout.addWidget(self.notify_check)

        notify_form = QFormLayout()
        notify_form.setSpacing(9)
        self.notify_spin = QSpinBox()
        self.notify_spin.setRange(1, 120)
        self.notify_spin.setSuffix(" хв до початку")
        notify_form.addRow("Час сповіщення", self.notify_spin)
        layout.addLayout(notify_form)

        # -------------------------------------------------------- пропущені пари
        catchup_label = QLabel("Якщо пару пропущено")
        catchup_label.setObjectName("SectionLabel")
        layout.addWidget(catchup_label)

        box = QFrame()
        choices = QVBoxLayout(box)
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setSpacing(2)
        self.catchup_group = QButtonGroup(self)
        for index, (value, label) in enumerate(CATCHUP_CHOICES):
            button = QRadioButton(label)
            button.setProperty("mode", value)
            self.catchup_group.addButton(button, index)
            choices.addWidget(button)
        layout.addWidget(box)

        catchup_hint = QLabel(
            "Пара, яка вже тривала на момент запуску AutoPara, ніколи не відкривається сама -- "
            "застосунок спершу питає, навіть у режимі «Відкрити одразу»."
        )
        catchup_hint.setObjectName("FormHint")
        catchup_hint.setWordWrap(True)
        layout.addWidget(catchup_hint)

        # ------------------------------------------------------------ автозапуск
        self.autostart_check = QCheckBox("Запускати AutoPara разом із Windows")
        layout.addWidget(self.autostart_check)

        hint = QLabel(
            "Автозапуск додає AutoPara до автозавантаження Windows і запускає його згорнутим у "
            "трей. Вимкнути можна також у Диспетчері завдань → Автозавантаження."
        )
        hint.setObjectName("FormHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.duration_hint = QLabel(
            "Тривалість пари впливає лише на пари, додані або імпортовані надалі."
        )
        self.duration_hint.setObjectName("FormHint")
        self.duration_hint.setWordWrap(True)
        layout.addWidget(self.duration_hint)

        # Кнопки шикуються вручну, а не через QDialogButtonBox: на Windows той ставить
        # головну дію ліворуч, а в цій мові інтерфейсу вона завжди крайня праворуч.
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)

        cancel = QPushButton("Скасувати")
        cancel.setObjectName("Plain")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)

        save = QPushButton("Зберегти")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        footer.addWidget(save)
        layout.addLayout(footer)

    # ------------------------------------------------------------------- state

    def _notify_toggled(self, enabled: bool) -> None:
        self.notify_spin.setEnabled(enabled)

    def _load(self) -> None:
        settings = self.storage.settings()
        self.lead_spin.setValue(settings.lead_minutes)
        self.duration_spin.setValue(settings.class_duration_minutes)
        self.notify_check.setChecked(settings.notifications_enabled)
        self.notify_spin.setValue(settings.notify_minutes)
        self.notify_spin.setEnabled(settings.notifications_enabled)

        index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, index))

        for button in self.catchup_group.buttons():
            if button.property("mode") == settings.catchup_mode:
                button.setChecked(True)
                break
        else:
            self.catchup_group.buttons()[0].setChecked(True)

        # Реєстр -- джерело правди: користувач міг вимкнути автозапуск у Диспетчері завдань.
        self.autostart_check.setChecked(autostart.is_enabled())

    def catchup_mode(self) -> str:
        button = self.catchup_group.checkedButton()
        return button.property("mode") if button else CATCHUP_NOTIFY

    def _accept(self) -> None:
        self.storage.set_setting("lead_minutes", self.lead_spin.value())
        self.storage.set_setting("class_duration_minutes", self.duration_spin.value())
        self.storage.set_setting("catchup_mode", self.catchup_mode())
        self.storage.set_setting("notifications_enabled", "1" if self.notify_check.isChecked() else "0")
        self.storage.set_setting("notify_minutes", self.notify_spin.value())
        self.storage.set_setting("theme", self.theme_combo.currentData())

        wanted = self.autostart_check.isChecked()
        if wanted != autostart.is_enabled():
            if not autostart.set_enabled(wanted):
                QMessageBox.warning(
                    self,
                    "Не вдалося змінити автозапуск",
                    "Windows відхилив зміну запису автозавантаження в реєстрі.",
                )
        self.storage.set_setting("autostart_enabled", "1" if autostart.is_enabled() else "0")
        self.accept()
