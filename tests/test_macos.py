"""macOS integration tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autopara.core import autostart, launcher, storage, theme
from autopara.ui import tray


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific tests")
class TestMacOSPlatformIntegration:
    def test_default_db_path_on_macos(self, monkeypatch):
        monkeypatch.delenv("APPDATA", raising=False)
        db_path = storage.default_db_path()
        assert db_path.parent.name == "AutoPara"
        assert "Library/Application Support/AutoPara" in str(db_path)

    def test_system_theme_detection_macos(self):
        current = theme.system_theme()
        assert current in (theme.THEME_DARK, theme.THEME_LIGHT)

    def test_mac_url_launching(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success = launcher.open_url("https://meet.google.com/test-room")
            assert success is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "open"
            assert "https://meet.google.com/test-room" in args

    def test_mac_autostart_cycle(self, tmp_path, monkeypatch):
        test_plist = tmp_path / "LaunchAgents" / "com.autopara.app.plist"
        monkeypatch.setattr(autostart, "MAC_PLIST_PATH", test_plist)

        assert autostart.is_enabled() is False
        assert autostart.enable() is True
        assert test_plist.is_file()
        assert autostart.is_enabled() is True

        content = test_plist.read_text(encoding="utf-8")
        assert "com.autopara.app" in content
        assert "--hidden" in content

        assert autostart.disable() is True
        assert autostart.is_enabled() is False
        assert not test_plist.exists()

    def test_write_icns_generation(self, tmp_path, gui_app):
        icns_file = tmp_path / "AutoPara.icns"
        tray.write_icns(icns_file)
        assert icns_file.is_file()
        assert icns_file.stat().st_size > 50000
