"""Guards on the NSIS installer script.

The installer is the one part of the project that cannot be exercised from pytest -- running it
installs the app. What *can* be checked is that the script keeps agreeing with the code it ships,
and every assertion here exists because the two drifting apart fails silently:

* the autostart command must match what the app itself writes, or the settings screen shows the
  entry as disabled and rewrites it on the next launch;
* the window title it looks for must match the app's, or "AutoPara is running" never triggers and
  the install writes over locked files. That had already drifted once, when the UI was translated.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

NSI_PATH = Path(__file__).resolve().parents[1] / "installer" / "AutoPara.nsi"


@pytest.fixture(scope="module")
def script() -> str:
    if not NSI_PATH.is_file():
        pytest.skip(f"{NSI_PATH} not found")
    # The file is UTF-8 with a BOM; makensis needs the BOM to read the Ukrainian strings.
    return NSI_PATH.read_text(encoding="utf-8-sig")


def define(script: str, name: str) -> str:
    """Read a !define value, joining NSIS backslash line continuations first."""
    joined = re.sub(r"\\\s*\n\s*", " ", script)
    match = re.search(rf'^!define\s+{name}\s+"(.*)"\s*$', joined, re.MULTILINE)
    assert match, f"!define {name} not found in the installer script"
    return match.group(1)


class TestEncoding:
    def test_file_is_utf8_with_bom(self):
        """Without the BOM makensis falls back to the code page and mangles the Ukrainian text."""
        assert NSI_PATH.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_unicode_mode_is_on(self, script):
        assert re.search(r"^Unicode true", script, re.MULTILINE)


class TestAgreesWithTheApplication:
    def test_autostart_command_matches_what_the_app_writes(self, script):
        """The installer and autostart.startup_command() must produce the same string.

        If they diverge, autostart.sync() silently rewrites the installer's entry on first launch.
        """
        from autopara.core import autostart

        written = re.search(
            r'WriteRegStr\s+HKCU\s+"\$\{RUN_KEY\}"\s+"\$\{APP_NAME\}"\s+\'(.+)\'',
            script,
        )
        assert written, "the autostart section does not write a Run value"
        installer_command = written.group(1).replace("$INSTDIR\\${APP_EXE}", "{exe}")

        # What the frozen app produces, with the executable path stubbed the same way.
        app_command = autostart.startup_command()
        frozen_shape = '"{exe}" --hidden'
        assert installer_command == frozen_shape
        assert app_command.endswith("--hidden"), "the app must also start hidden"
        assert app_command.startswith('"'), "the path must be quoted, it contains spaces"

    def test_window_title_matches_the_running_app(self, script):
        """FindWindow needs the exact title, or the 'is it running?' check never fires."""
        from autopara.ui import main_window

        source = Path(main_window.__file__).read_text(encoding="utf-8")
        title = re.search(r'setWindowTitle\(\s*"([^"]+)"\s*\)', source)
        assert title, "MainWindow.setWindowTitle not found"

        assert define(script, "APP_DISPLAY") == title.group(1)
        assert 'FindWindow $0 "" "${APP_DISPLAY}"' in script

    def test_data_directory_matches_the_one_storage_uses(self, script):
        """The uninstaller offers to delete the app's data; it must name the right folder."""
        from autopara.core.storage import default_db_path

        assert default_db_path().parent.name == "AutoPara"
        assert '$APPDATA\\${APP_NAME}' in script


class TestInstallReplacesRatherThanMerges:
    def test_the_bundle_directory_is_purged_before_writing(self, script):
        """A module left from an older bundle stays importable and wins over nothing."""
        purge = script.index('RMDir /r "$INSTDIR\\_internal"')
        write = script.index('File /r "..\\dist\\AutoPara\\*.*"')
        assert purge < write, "the old bundle must be removed before the new one is written"


class TestSilentModeNeverBlocks:
    @pytest.mark.parametrize("guard", ["skip_running_check", "keep_data"])
    def test_every_messagebox_is_guarded_by_ifsilent(self, script, guard):
        """/S install and uninstall would hang forever on an invisible message box."""
        assert f"IfSilent {guard}" in script

    def test_no_unguarded_messagebox_remains(self, script):
        """Each MessageBox must have an IfSilent before it."""
        silent_positions = [m.start() for m in re.finditer(r"IfSilent\s+\w+", script)]
        for box in re.finditer(r"^\s*MessageBox\s", script, re.MULTILINE):
            assert any(pos < box.start() for pos in silent_positions), (
                f"MessageBox at offset {box.start()} is not preceded by an IfSilent guard"
            )


class TestUninstall:
    def test_it_keeps_the_imported_timetable_by_default(self, script):
        """Reinstalling must not lose the schedule, so deleting the data is opt-in."""
        uninstall = script[script.index('Section "Uninstall"'):]
        delete_data = uninstall.index('RMDir /r "$APPDATA\\${APP_NAME}"')
        guard = uninstall.index("IfSilent keep_data")
        assert guard < delete_data, "a silent uninstall must skip the data deletion"
        assert "IDNO keep_data" in uninstall, "answering No must keep the data"

    def test_it_removes_both_registry_entries(self, script):
        uninstall = script[script.index('Section "Uninstall"'):]
        assert 'DeleteRegValue HKCU "${RUN_KEY}" "${APP_NAME}"' in uninstall
        assert 'DeleteRegKey   HKCU "${UNINST_KEY}"' in uninstall


class TestPerUserInstall:
    def test_no_admin_rights_are_requested(self, script):
        """A per-user install raises no UAC prompt, which matters on a borrowed PC."""
        assert re.search(r"^RequestExecutionLevel user", script, re.MULTILINE)

    def test_it_installs_under_localappdata(self, script):
        assert 'InstallDir "$LOCALAPPDATA\\Programs\\${APP_NAME}"' in script

    def test_registry_writes_are_all_hkcu(self, script):
        """A per-user install must never touch HKLM; it would fail without elevation."""
        assert "HKLM" not in script


class TestInterfaceIsUkrainian:
    """The app's UI is Ukrainian, so the installer the same user sees must be too."""

    def test_ukrainian_language_is_selected(self, script):
        assert '!insertmacro MUI_LANGUAGE "Ukrainian"' in script

    def test_user_visible_strings_are_ukrainian(self, script):
        cyrillic = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
        for macro in ("MUI_FINISHPAGE_RUN_TEXT", "MUI_FINISHPAGE_TEXT"):
            assert cyrillic.search(define(script, macro)), f"{macro} is not Ukrainian"

        sections = re.findall(r'^Section\s+"([^"]+)"\s+SEC_', script, re.MULTILINE)
        assert sections, "no installer sections found"
        for name in sections:
            assert cyrillic.search(name), f"section name is not Ukrainian: {name}"

        for description in re.findall(r"^LangString\s+DESC_\w+\s+\$\{LANG_UKRAINIAN\}\s+\"(.+?)\"",
                                      script, re.MULTILINE | re.DOTALL):
            assert cyrillic.search(description)


class TestThereIsOnlyOneInstaller:
    """The project deliberately ships one installer; a second one drifts out of date."""

    def test_the_source_installer_is_gone(self):
        root = NSI_PATH.parents[1]
        for stale in ("installer.exe", "installer.cmd",
                      "installer/install_app.py", "installer/build_installer.ps1"):
            assert not (root / stale).exists(), f"{stale} should have been removed"

    def test_build_script_drives_the_nsis_installer(self):
        build = (NSI_PATH.parents[1] / "build.ps1").read_text(encoding="utf-8")
        assert "makensis" in build
        assert "AutoPara.nsi" in build
