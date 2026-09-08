# Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
# PyInstaller spec for AutoPara.
#
# Built as --onedir --noconsole:
#   * onedir starts noticeably faster than onefile, which matters for an app that launches at
#     boot alongside everything else Windows starts.
#   * noconsole (windowed) keeps a console window from flashing when Windows runs it at logon.
#
# Build with:  python -m PyInstaller AutoPara.spec --noconfirm

block_cipher = None

# Windows reads the executable's icon from a compiled-in .ico, so build.ps1 renders one from the
# app's own drawing (autopara/ui/tray.write_ico) before invoking PyInstaller. Building the spec by
# hand without that step is allowed -- the bundle just carries PyInstaller's stock icon, which is
# the Python logo, and the desktop shortcut with it.
import os

APP_ICON = os.path.join("build", "AutoPara.ico")
if not os.path.isfile(APP_ICON):
    print(f"AutoPara.spec: {APP_ICON} is missing; the exe will keep PyInstaller's stock icon")
    APP_ICON = None

analysis = Analysis(
    ["autopara_launch.pyw"],
    pathex=["."],
    binaries=[],
    datas=[
        ("autopara/ui/styles.qss", "autopara/ui"),
        # Google Sans and its licence: the interface font is bundled, not assumed installed.
        ("autopara/ui/fonts", "autopara/ui/fonts"),
    ],
    hiddenimports=["autopara"],
    hookspath=[],
    runtime_hooks=[],
    # Qt modules the app never touches; excluding them keeps the bundle far smaller.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "PySide6.QtBluetooth",
        "PySide6.QtDesigner",
        "PySide6.QtTest",
        "tkinter",
        "pytest",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AutoPara",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no console window at logon
    icon=APP_ICON,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoPara",
)
