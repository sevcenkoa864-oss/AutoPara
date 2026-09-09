#!/usr/bin/env python3
"""Build script for AutoPara on macOS.

Generates the native Retina icon (.icns), bundles the application into AutoPara.app
via PyInstaller, and packages it into a drag-to-install AutoPara.dmg image.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "darwin":
        print("Error: build_mac.py must be run on macOS.", file=sys.stderr)
        return 1

    root = Path(__file__).resolve().parent
    os.chdir(root)

    print("==> 1. Generating macOS Retina icon (build/AutoPara.icns)...")
    build_dir = root / "build"
    build_dir.mkdir(exist_ok=True)
    icns_path = build_dir / "AutoPara.icns"

    # We need a QApplication to render the icon pixmaps offscreen
    cmd_gen_icon = [
        sys.executable,
        "-c",
        (
            "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; "
            "from PySide6.QtWidgets import QApplication; "
            "app = QApplication([]); "
            "from autopara.ui.tray import write_icns; "
            f"write_icns('{icns_path}'); "
            "print('Icon written successfully.')"
        ),
    ]
    res = subprocess.run(cmd_gen_icon)
    if res.returncode != 0 or not icns_path.is_file():
        print("Error: Failed to generate AutoPara.icns", file=sys.stderr)
        return 1
    print(f"    Icon ready: {icns_path} ({icns_path.stat().st_size // 1024} KB)")

    print("==> 2. Building AutoPara.app with PyInstaller...")
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "AutoPara.spec",
        "--noconfirm",
    ]
    res = subprocess.run(pyinstaller_cmd)
    if res.returncode != 0:
        print("Error: PyInstaller build failed.", file=sys.stderr)
        return 1

    app_path = root / "dist" / "AutoPara.app"
    if not app_path.is_dir():
        print(f"Error: Expected {app_path} to exist.", file=sys.stderr)
        return 1
    print(f"    Application bundle created at: {app_path}")

    print("==> 3. Creating drag-and-drop installer DMG (dist/AutoPara.dmg)...")
    dmg_staging = build_dir / "dmg_staging"
    if dmg_staging.exists():
        shutil.rmtree(dmg_staging)
    dmg_staging.mkdir(parents=True)

    # Copy AutoPara.app into staging
    subprocess.run(["cp", "-R", str(app_path), str(dmg_staging / "AutoPara.app")], check=True)

    # Create Applications symlink for drag-and-drop
    apps_link = dmg_staging / "Applications"
    os.symlink("/Applications", str(apps_link))

    dmg_path = root / "dist" / "AutoPara.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    hdiutil_cmd = [
        "hdiutil",
        "create",
        "-volname",
        "AutoPara",
        "-srcfolder",
        str(dmg_staging),
        "-ov",
        "-format",
        "UDZO",
        str(dmg_path),
    ]
    res = subprocess.run(hdiutil_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Warning: hdiutil failed: {res.stderr}", file=sys.stderr)
    else:
        print(f"    DMG installer created at: {dmg_path} ({dmg_path.stat().st_size // (1024*1024)} MB)")

    print("\n✅ AutoPara macOS build completed successfully!")
    print(f"   • Standalone App: {app_path}")
    if dmg_path.is_file():
        print(f"   • DMG Installer:  {dmg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
