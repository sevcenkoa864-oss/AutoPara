"""The installer's file handling: a reinstall replaces, it does not merge.

Only the filesystem steps are exercised. Creating the virtual environment downloads PySide6 and
takes minutes, and writing to the registry or launching the app would touch the machine running
the suite; those are left to a real install.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import pytest

from installer import install_app


@pytest.fixture
def payload(tmp_path, monkeypatch):
    """A stand-in for the files the installer carries."""
    root = tmp_path / "payload"
    (root / "autopara" / "core").mkdir(parents=True)
    (root / "autopara" / "app.py").write_text("VERSION = 'new'\n", encoding="utf-8")
    (root / "autopara" / "core" / "storage.py").write_text("# new\n", encoding="utf-8")
    (root / "autopara" / "__pycache__").mkdir()
    (root / "autopara" / "__pycache__" / "app.pyc").write_bytes(b"stale")
    (root / "autopara_launch.pyw").write_text("launch\n", encoding="utf-8")
    (root / "requirements.txt").write_text("PySide6>=6.8\n", encoding="utf-8")
    monkeypatch.setattr(install_app, "payload_root", lambda: root)
    return root


@pytest.fixture
def data(tmp_path, monkeypatch):
    """%APPDATA%\\AutoPara as a previous install would have left it."""
    root = tmp_path / "appdata"
    (root / "schedules").mkdir(parents=True)
    (root / "schedules" / "timetable.docx").write_bytes(b"the imported document")
    (root / "autopara.db").write_bytes(b"old database")
    (root / "autopara.log").write_text("old log\n", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "check-light.png").write_bytes(b"old asset")
    monkeypatch.setattr(install_app, "data_dir", lambda: root)
    return root


@pytest.fixture
def previous(tmp_path):
    """An earlier installation, including a module the new version no longer ships."""
    root = tmp_path / "AutoPara"
    (root / "autopara").mkdir(parents=True)
    (root / "autopara" / "app.py").write_text("VERSION = 'old'\n", encoding="utf-8")
    (root / "autopara" / "removed_module.py").write_text("# gone upstream\n", encoding="utf-8")
    (root / "runtime").mkdir()
    (root / "runtime" / "python.exe").write_bytes(b"pretend interpreter")
    return root


def make(target, log=None):
    return install_app.Installation(
        target, desktop_shortcut=False, autostart=False, log=log or (lambda _: None)
    )


class TestReinstallReplaces:
    def test_the_old_install_directory_is_removed_whole(self, payload, data, previous):
        install = make(previous)
        install.purge_previous()
        assert not previous.exists()

    def test_a_module_dropped_upstream_does_not_survive(self, payload, data, previous):
        """A leftover module is importable and beats nothing -- this is why 'nothing changed'."""
        install = make(previous)
        install.purge_previous()
        install.copy_payload()

        assert (previous / "autopara" / "app.py").read_text(encoding="utf-8") == "VERSION = 'new'\n"
        assert not (previous / "autopara" / "removed_module.py").exists()

    def test_bytecode_is_never_copied(self, payload, data, previous):
        install = make(previous)
        install.purge_previous()
        install.copy_payload()
        assert not (previous / "autopara" / "__pycache__").exists()

    def test_only_the_imported_document_survives(self, payload, data, previous):
        """Everything else the app wrote goes, so a reinstall really is a fresh start."""
        make(previous).purge_previous()

        assert (data / "schedules" / "timetable.docx").read_bytes() == b"the imported document"
        assert not (data / "autopara.db").exists()
        assert not (data / "autopara.log").exists()
        assert not (data / "assets").exists()

    def test_installing_where_nothing_was_installed_is_fine(self, payload, data, tmp_path):
        fresh = tmp_path / "fresh"
        install = make(fresh)
        install.purge_previous()
        install.copy_payload()
        assert (fresh / "autopara" / "app.py").is_file()


class TestUninstallerScript:
    def test_it_removes_the_data_directory_too(self, payload, data, tmp_path):
        """Uninstalling clears everything, the archived timetable included."""
        target = tmp_path / "AutoPara"
        target.mkdir()
        make(target).write_uninstaller()

        script = (target / "Uninstall.cmd").read_text(encoding="ascii")
        assert f'rmdir /s /q "%APPDATA%\\{install_app.APP_NAME}"' in script
        assert str(target) in script
        assert install_app.RUN_KEY in script
        assert install_app.APP_KEY in script

    def test_the_script_is_ascii_so_the_console_can_read_it(self, payload, data, tmp_path):
        target = tmp_path / "AutoPara"
        target.mkdir()
        make(target).write_uninstaller()
        # Decodes as ASCII or this raises -- a .cmd is read in the console code page.
        (target / "Uninstall.cmd").read_bytes().decode("ascii")


class TestLaunchCommand:
    def test_matches_what_the_app_writes_for_autostart(self, payload, tmp_path):
        """If the two ever differ, autostart.sync() rewrites the entry on the next launch."""
        target = tmp_path / "AutoPara"
        command = make(target).launch_command(hidden=True)
        assert command.endswith(' --hidden')
        assert str(target / "autopara_launch.pyw") in command
        assert "pythonw.exe" in command or "python.exe" in command
