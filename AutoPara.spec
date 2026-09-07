# PyInstaller spec for AutoPara.
#
# Built as --onedir --noconsole:
#   * onedir starts noticeably faster than onefile, which matters for an app that launches at
#     boot alongside everything else Windows starts.
#   * noconsole (windowed) keeps a console window from flashing when Windows runs it at logon.
#
# Build with:  python -m PyInstaller AutoPara.spec --noconfirm

block_cipher = None

analysis = Analysis(
    ["autopara_launch.pyw"],
    pathex=["."],
    binaries=[],
    datas=[("autopara/ui/styles.qss", "autopara/ui")],
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
