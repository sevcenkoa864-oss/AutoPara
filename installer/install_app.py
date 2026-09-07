"""Встановлювач AutoPara — той самий код, що й у `installer.exe` в корені репозиторію.

Мета: користувач завантажує репозиторій, запускає `installer.exe` (або `installer.cmd`), обирає
теку, і в кінці отримує робочий застосунок, який одразу запускається.

Чому саме tkinter і жодних залежностей: встановлювач мусить працювати на машині, де ще нічого не
встановлено. tkinter входить до стандартної поставки CPython для Windows, тож встановлювач
запуститься навіть тоді, коли PySide6 ще немає — а він її і поставить.

Порядок дій:

1. Перевірка середовища ("dev kits"): інтерпретатор Python потрібної версії, модуль ``venv``,
   ``pip``. Чого бракує — ставиться через термінал (``winget`` для самого Python, ``pip`` для
   решти), і встановлення продовжується.
2. Копіювання застосунку в обрану теку.
3. Власне середовище виконання: ізольований ``venv`` усередині теки встановлення з PySide6.
   Так застосунок не залежить від системних пакетів і не ламається, коли їх оновлять.
4. Ярлики, запис автозавантаження (увімкнено типово) і запис у «Програми та засоби».
5. Запуск AutoPara.

Перевстановлення -- це заміна, а не накладання. Стара тека видаляється цілком, а разом із нею й
дані застосунку, крім збереженої копії розкладу (.docx). Інакше модуль, який колись перейменували,
лишається на диску, і Python радо його імпортує -- саме через це «нова» версія поводилася як
стара. Єдине, що переживає перевстановлення, -- тека schedules з копією документа.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "AutoPara"
APP_DISPLAY = "AutoPara — автозапуск пар"
APP_VERSION = "1.2.0"

MIN_PYTHON = (3, 10)
WINGET_PYTHON_ID = "Python.Python.3.13"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
APP_KEY = rf"Software\{APP_NAME}"

# Єдине, що переживає перевстановлення: копія імпортованого розкладу.
KEEP_ON_REINSTALL = {"schedules"}

# Те, що переноситься в теку встановлення. Тести й будівельні скрипти користувачеві не потрібні.
PAYLOAD_ITEMS = [
    "autopara",
    "autopara_launch.pyw",
    "requirements.txt",
    "README.md",
    "docs",
]

# Приховати консольні вікна дочірніх процесів: встановлювач збирається як віконний застосунок,
# і кожен pip без цього блимав би чорним прямокутником.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    import winreg
except ImportError:  # pragma: no cover - не Windows
    winreg = None


class InstallError(RuntimeError):
    """Помилка, яку варто показати користувачеві як є."""


def payload_root() -> Path:
    """Тека з файлами застосунку: усередині зібраного .exe або корінь репозиторію."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "payload"
    return Path(__file__).resolve().parents[1]


def default_target() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP_NAME


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def run_command(command: list[str], log, cwd: Path | None = None) -> int:
    """Виконати команду в терміналі, віддаючи її вивід у журнал встановлення."""
    log("> " + " ".join(command))
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            log("  " + line)
    return process.wait()


# --------------------------------------------------------------------- перевірки


def _python_version(executable: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [executable, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        major, minor = (int(part) for part in result.stdout.split())
    except ValueError:
        return None
    return major, minor


def _real_executable(candidate: list[str]) -> str | None:
    """Розгорнути ``py -3`` у справжній шлях до python.exe."""
    try:
        result = subprocess.run(
            [*candidate, "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = result.stdout.strip()
    return path if result.returncode == 0 and path else None


def find_python(log) -> str | None:
    """Знайти інтерпретатор, придатний для запуску AutoPara.

    Зібраний встановлювач має власний вбудований Python, але він не підходить застосунку: це
    той самий exe встановлювача. Тому шукаємо системний.
    """
    candidates: list[list[str]] = []
    if not getattr(sys, "frozen", False):
        candidates.append([sys.executable])
    candidates += [["py", "-3"], ["python"], ["python3"]]

    for candidate in candidates:
        executable = _real_executable(candidate)
        if not executable:
            continue
        version = _python_version(executable)
        if version and version >= MIN_PYTHON:
            log(f"Знайдено Python {version[0]}.{version[1]}: {executable}")
            return executable
        if version:
            log(f"Пропущено Python {version[0]}.{version[1]} — потрібна "
                f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} або новіша: {executable}")
    return None


def install_python(log) -> str | None:
    """Поставити Python через winget і знайти його знову."""
    if shutil.which("winget") is None:
        raise InstallError(
            "На комп'ютері немає Python "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ і немає winget, щоб його встановити.\n\n"
            "Встановіть Python із python.org і запустіть встановлювач ще раз."
        )
    log(f"Python не знайдено — встановлюю {WINGET_PYTHON_ID} через winget…")
    code = run_command(
        [
            "winget", "install", "--exact", "--id", WINGET_PYTHON_ID,
            "--source", "winget", "--scope", "user",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity",
        ],
        log,
    )
    if code != 0:
        raise InstallError(
            "winget не зміг встановити Python (код виходу "
            f"{code}). Встановіть Python із python.org і повторіть спробу."
        )
    return find_python(log)


def check_module(executable: str, module: str, log) -> bool:
    result = subprocess.run(
        [executable, "-c", f"import {module}"],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    ok = result.returncode == 0
    log(f"  {module}: {'є' if ok else 'немає'}")
    return ok


# ------------------------------------------------------------------ встановлення


class Installation:
    """Кроки встановлення. Виконується у робочому потоці; ``log`` пише в інтерфейс."""

    def __init__(self, target: Path, desktop_shortcut: bool, autostart: bool, log):
        self.target = target
        self.desktop_shortcut = desktop_shortcut
        self.autostart = autostart
        self.log = log
        self.python: str | None = None

    # ------------------------------------------------------------------ кроки

    def verify_prerequisites(self) -> None:
        self.log("Перевіряю середовище…")
        self.python = find_python(self.log)
        if self.python is None:
            self.python = install_python(self.log)
        if self.python is None:
            raise InstallError("Не вдалося знайти або встановити Python.")

        self.log("Перевіряю потрібні модулі…")
        if not check_module(self.python, "venv", self.log):
            raise InstallError(
                "У цій збірці Python немає модуля venv. Встановіть звичайний Python із "
                "python.org (у Microsoft Store venv буває вирізаний) і повторіть спробу."
            )
        if not check_module(self.python, "ensurepip", self.log):
            raise InstallError(
                "У цій збірці Python немає pip. Перевстановіть Python із python.org."
            )
        if not check_module(self.python, "tkinter", self.log):
            # Не критично для самого застосунку — лише попередження.
            self.log("  (tkinter недоступний, але AutoPara його не потребує)")

    def purge_previous(self) -> None:
        """Прибрати попереднє встановлення повністю, лишивши тільки копію розкладу.

        Копіювання «поверх» лишає модулі, які в новій версії видалили або перейменували, і
        Python імпортує саме їх. Тому стара тека йде цілком, разом з базою й налаштуваннями;
        уціліє лише schedules із .docx, щоб не довелося шукати документ наново.
        """
        if self.target.exists():
            self.log(f"Видаляю попереднє встановлення в {self.target}…")
            shutil.rmtree(self.target, ignore_errors=True)
            if self.target.exists():
                raise InstallError(
                    f"Не вдалося очистити теку {self.target}.\n\n"
                    "Найімовірніше, AutoPara ще запущено — вийдіть із нього через значок у "
                    "треї й повторіть."
                )

        data = data_dir()
        if not data.exists():
            return
        self.log("Очищую старі дані застосунку (копія розкладу лишається)…")
        for item in data.iterdir():
            if item.name in KEEP_ON_REINSTALL:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    item.unlink()
                except OSError:
                    self.log(f"  не вдалося видалити {item.name} (пропущено)")

    def copy_payload(self) -> None:
        source = payload_root()
        self.log(f"Копіюю застосунок у {self.target}…")
        self.target.mkdir(parents=True, exist_ok=True)
        for name in PAYLOAD_ITEMS:
            origin = source / name
            if not origin.exists():
                self.log(f"  пропущено (немає у збірці): {name}")
                continue
            destination = self.target / name
            if origin.is_dir():
                shutil.copytree(
                    origin,
                    destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            else:
                shutil.copy2(origin, destination)
            self.log(f"  {name}")

    def create_runtime(self) -> None:
        """Власний venv усередині теки встановлення — застосунок не залежить від системних пакетів."""
        runtime = self.target / "runtime"
        self.log("Створюю середовище виконання…")
        if run_command([self.python, "-m", "venv", str(runtime)], self.log) != 0:
            raise InstallError("Не вдалося створити віртуальне середовище.")

        python = self.runtime_python()
        run_command([str(python), "-m", "pip", "install", "--upgrade", "pip"], self.log)
        self.log("Встановлюю PySide6 (це найдовший крок)…")
        requirements = self.target / "requirements.txt"
        command = [str(python), "-m", "pip", "install"]
        command += ["-r", str(requirements)] if requirements.exists() else ["PySide6>=6.8"]
        if run_command(command, self.log) != 0:
            raise InstallError(
                "Не вдалося встановити PySide6. Перевірте з'єднання з інтернетом і повторіть."
            )

    def runtime_python(self) -> Path:
        return self.target / "runtime" / "Scripts" / "python.exe"

    def runtime_pythonw(self) -> Path:
        windowed = self.target / "runtime" / "Scripts" / "pythonw.exe"
        return windowed if windowed.exists() else self.runtime_python()

    def launch_command(self, hidden: bool = False) -> str:
        """Той самий рядок, який будує autostart.startup_command() для запуску з коду."""
        suffix = " --hidden" if hidden else ""
        return f'"{self.runtime_pythonw()}" "{self.target / "autopara_launch.pyw"}"{suffix}'

    def create_shortcuts(self) -> None:
        self.log("Створюю ярлики…")
        start_menu = (
            Path(os.environ.get("APPDATA", Path.home()))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
        )
        start_menu.mkdir(parents=True, exist_ok=True)
        self._shortcut(start_menu / f"{APP_NAME}.lnk")
        if self.desktop_shortcut:
            desktop = Path(os.path.expanduser("~")) / "Desktop"
            if desktop.is_dir():
                self._shortcut(desktop / f"{APP_NAME}.lnk")

    def _shortcut(self, path: Path) -> None:
        """Ярлик через WScript.Shell: pywin32 у стандартній поставці немає, PowerShell — є."""
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
            "$s.TargetPath = '{target}';"
            "$s.Arguments = '\"{script}\"';"
            "$s.WorkingDirectory = '{workdir}';"
            "$s.Description = '{description}';"
            "$s.Save()"
        ).format(
            link=path,
            target=self.runtime_pythonw(),
            script=self.target / "autopara_launch.pyw",
            workdir=self.target,
            description=APP_DISPLAY,
        )
        code = run_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], self.log
        )
        if code != 0:
            self.log(f"  не вдалося створити ярлик {path.name} (пропущено)")
        else:
            self.log(f"  {path}")

    def write_uninstaller(self) -> None:
        script = self.target / "Uninstall.cmd"
        # ASCII в самому .cmd: командний рядок читає файл у кодовій сторінці консолі, і
        # кирилиця тут перетворилася б на кашу.
        script.write_text(
            "@echo off\r\n"
            f"echo Uninstalling {APP_NAME}...\r\n"
            f'reg delete "HKCU\\{RUN_KEY}" /v {APP_NAME} /f >nul 2>&1\r\n'
            f'reg delete "HKCU\\{UNINSTALL_KEY}" /f >nul 2>&1\r\n'
            f'reg delete "HKCU\\{APP_KEY}" /f >nul 2>&1\r\n'
            f'del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}\\*.lnk" '
            ">nul 2>&1\r\n"
            f'rmdir "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}" '
            ">nul 2>&1\r\n"
            f'del /q "%USERPROFILE%\\Desktop\\{APP_NAME}.lnk" >nul 2>&1\r\n'
            # Uninstalling removes everything, the archived timetable included.
            f'rmdir /s /q "%APPDATA%\\{APP_NAME}" >nul 2>&1\r\n'
            "echo Done.\r\n"
            f'start "" cmd /c timeout /t 2 ^&^& rmdir /s /q "{self.target}"\r\n',
            encoding="ascii",
        )
        self.log(f"  {script}")

    def register(self) -> None:
        if winreg is None:  # pragma: no cover - не Windows
            return
        self.log("Реєструю застосунок…")
        self.write_uninstaller()
        # ``python -m autopara`` reads this back to know which installation to refresh.
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, APP_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "InstallDir", 0, winreg.REG_SZ, str(self.target))
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_DISPLAY)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(self.target))
            winreg.SetValueEx(
                key, "UninstallString", 0, winreg.REG_SZ, f'"{self.target / "Uninstall.cmd"}"'
            )
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)

        if self.autostart:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(
                    key, APP_NAME, 0, winreg.REG_SZ, self.launch_command(hidden=True)
                )
            self.log("  автозапуск разом із Windows увімкнено")

    def launch(self) -> None:
        self.log("Запускаю AutoPara…")
        subprocess.Popen(
            [str(self.runtime_pythonw()), str(self.target / "autopara_launch.pyw")],
            cwd=str(self.target),
            creationflags=NO_WINDOW,
        )

    # ------------------------------------------------------------------- усе

    def run(self) -> None:
        self.verify_prerequisites()
        self.purge_previous()
        self.copy_payload()
        self.create_runtime()
        self.create_shortcuts()
        self.register()
        self.launch()


# ------------------------------------------------------------------- інтерфейс


class InstallerWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Встановлення {APP_DISPLAY}")
        self.geometry("680x480")
        self.minsize(600, 420)
        self._messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._build()
        self.after(80, self._drain)

    def _build(self) -> None:
        padding = {"padx": 14, "pady": 6}

        header = ttk.Label(
            self,
            text=f"{APP_DISPLAY}  {APP_VERSION}",
            font=("Segoe UI", 14, "bold"),
        )
        header.pack(anchor="w", **padding)

        ttk.Label(
            self,
            text=(
                "Встановлювач перевірить потрібні компоненти, за потреби встановить їх, "
                "скопіює застосунок і запустить його."
            ),
            wraplength=630,
        ).pack(anchor="w", padx=14)

        row = ttk.Frame(self)
        row.pack(fill="x", **padding)
        ttk.Label(row, text="Тека встановлення:").pack(side="left")
        self.path_var = tk.StringVar(value=str(default_target()))
        ttk.Entry(row, textvariable=self.path_var).pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.browse_button = ttk.Button(row, text="Огляд…", command=self._browse)
        self.browse_button.pack(side="left")

        options = ttk.Frame(self)
        options.pack(fill="x", padx=14)
        self.desktop_var = tk.BooleanVar(value=True)
        self.autostart_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options, text="Ярлик на робочому столі", variable=self.desktop_var
        ).pack(anchor="w")
        ttk.Checkbutton(
            options,
            text="Запускати разом із Windows (рекомендовано)",
            variable=self.autostart_var,
        ).pack(anchor="w")

        self.log_widget = tk.Text(self, height=14, wrap="none", state="disabled")
        self.log_widget.pack(fill="both", expand=True, padx=14, pady=(10, 4))

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=14)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", **padding)
        self.install_button = ttk.Button(buttons, text="Встановити", command=self._install)
        self.install_button.pack(side="right")
        self.close_button = ttk.Button(buttons, text="Закрити", command=self.destroy)
        self.close_button.pack(side="right", padx=8)

    # ---------------------------------------------------------------- журнал

    def log(self, message: str) -> None:
        self._messages.put(("log", message))

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", payload + "\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
            elif kind == "done":
                self._finished(payload)
        self.after(80, self._drain)

    # --------------------------------------------------------------- дії

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(title="Оберіть теку для встановлення")
        if chosen:
            self.path_var.set(str(Path(chosen) / APP_NAME))

    def _install(self) -> None:
        target = Path(self.path_var.get().strip())
        if not target.drive:
            messagebox.showerror("Хибний шлях", "Вкажіть повний шлях до теки встановлення.")
            return
        if target.exists() and any(target.iterdir()):
            proceed = messagebox.askyesno(
                "Тека не порожня",
                f"{target}\n\nВміст буде видалено, а застосунок встановлено наново.\n"
                "Копія розкладу (.docx) збережеться. Продовжити?",
            )
            if not proceed:
                return

        self.install_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.progress.start(12)

        installation = Installation(
            target, self.desktop_var.get(), self.autostart_var.get(), self.log
        )

        def work() -> None:
            try:
                installation.run()
            except InstallError as error:
                self._messages.put(("done", str(error)))
            except Exception as error:  # несподіване — показати текст, не мовчати
                self._messages.put(("done", f"{type(error).__name__}: {error}"))
            else:
                self._messages.put(("done", ""))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _finished(self, error: str) -> None:
        self.progress.stop()
        self.install_button.configure(state="normal")
        self.browse_button.configure(state="normal")
        if error:
            self.log("ПОМИЛКА: " + error)
            messagebox.showerror("Встановлення не завершено", error)
            return
        self.log("Готово. AutoPara запущено.")
        messagebox.showinfo(
            "Встановлення завершено",
            f"{APP_NAME} встановлено в:\n{self.path_var.get()}\n\nЗастосунок уже запущено.",
        )
        self.destroy()


def main() -> int:
    if sys.platform != "win32":
        print("Встановлювач AutoPara працює лише у Windows.", file=sys.stderr)
        return 1
    InstallerWindow().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
