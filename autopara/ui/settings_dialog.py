"""Lead time, class length, catch-up policy and autostart."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..core import autostart
from ..core.models import CATCHUP_MISSED, CATCHUP_NOTIFY, CATCHUP_OPEN
from ..core.storage import Storage

CATCHUP_CHOICES = [
    (CATCHUP_NOTIFY, "Notify me, then open when I click"),
    (CATCHUP_OPEN, "Open it immediately"),
    (CATCHUP_MISSED, "Just mark it missed"),
]


class SettingsDialog(QDialog):
    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(9)

        self.lead_spin = QSpinBox()
        self.lead_spin.setRange(0, 120)
        self.lead_spin.setSuffix(" min before")
        form.addRow("Open link", self.lead_spin)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(10, 240)
        self.duration_spin.setSuffix(" min")
        form.addRow("Class length", self.duration_spin)

        self.catchup_combo = QComboBox()
        for value, label in CATCHUP_CHOICES:
            self.catchup_combo.addItem(label, value)
        form.addRow("If a class was missed", self.catchup_combo)

        layout.addLayout(form)

        self.autostart_check = QCheckBox("Start AutoPara when Windows starts")
        layout.addWidget(self.autostart_check)

        hint = QLabel(
            "Autostart adds AutoPara to your Windows startup apps and launches it hidden in the "
            "system tray. You can also turn it off from Task Manager → Startup."
        )
        hint.setObjectName("FormHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.duration_hint = QLabel(
            "Class length only affects classes added or re-imported from now on."
        )
        self.duration_hint.setObjectName("FormHint")
        self.duration_hint.setWordWrap(True)
        layout.addWidget(self.duration_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self) -> None:
        settings = self.storage.settings()
        self.lead_spin.setValue(settings.lead_minutes)
        self.duration_spin.setValue(settings.class_duration_minutes)
        index = self.catchup_combo.findData(settings.catchup_mode)
        self.catchup_combo.setCurrentIndex(max(0, index))
        # Trust the registry over the stored flag: the user may have disabled it in Task Manager.
        self.autostart_check.setChecked(autostart.is_enabled())

    def _accept(self) -> None:
        self.storage.set_setting("lead_minutes", self.lead_spin.value())
        self.storage.set_setting("class_duration_minutes", self.duration_spin.value())
        self.storage.set_setting("catchup_mode", self.catchup_combo.currentData())

        wanted = self.autostart_check.isChecked()
        if wanted != autostart.is_enabled():
            if not autostart.set_enabled(wanted):
                QMessageBox.warning(
                    self,
                    "Could not change autostart",
                    "Windows refused the change to the startup registry entry.",
                )
        self.storage.set_setting("autostart_enabled", "1" if autostart.is_enabled() else "0")
        self.accept()
