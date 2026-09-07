"""The rebuild step that a source run performs before starting.

These tests are pure filesystem work -- no Qt, no registry. What they pin down is the one thing
that made "reinstall and check" untrustworthy: a refresh must *replace* the directories it owns,
never merge into them, or a module deleted in the new version stays importable in the old one.

Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
"""

from __future__ import annotations

import pytest

from autopara.core import refresh


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A miniature checkout, standing in for the repository."""
    root = tmp_path / "src"
    (root / "autopara" / "core").mkdir(parents=True)
    (root / "autopara" / "app.py").write_text("VERSION = 'new'\n", encoding="utf-8")
    (root / "autopara" / "core" / "storage.py").write_text("# new\n", encoding="utf-8")
    (root / "autopara" / "__pycache__").mkdir()
    (root / "autopara" / "__pycache__" / "app.pyc").write_bytes(b"stale")
    (root / "autopara_launch.pyw").write_text("launch\n", encoding="utf-8")
    (root / "requirements.txt").write_text("PySide6>=6.8\n", encoding="utf-8")
    monkeypatch.setattr(refresh, "source_root", lambda: root)
    monkeypatch.setattr(refresh, "is_frozen", lambda: False)
    return root


@pytest.fixture
def installed(tmp_path):
    """A previous installation, complete with a module the new version no longer has."""
    root = tmp_path / "installed"
    (root / "autopara" / "core").mkdir(parents=True)
    (root / "autopara" / "app.py").write_text("VERSION = 'old'\n", encoding="utf-8")
    (root / "autopara" / "core" / "storage.py").write_text("# old\n", encoding="utf-8")
    (root / "autopara" / "removed_module.py").write_text("# gone upstream\n", encoding="utf-8")
    (root / "autopara" / "__pycache__").mkdir()
    (root / "autopara" / "__pycache__" / "removed_module.pyc").write_bytes(b"stale")
    (root / "runtime").mkdir()
    (root / "runtime" / "python.exe").write_bytes(b"pretend interpreter")
    return root


class TestRefresh:
    def test_copies_the_current_source_over(self, source, installed):
        assert refresh.refresh_installation(installed) == installed
        assert (installed / "autopara" / "app.py").read_text(encoding="utf-8") == "VERSION = 'new'\n"
        assert (installed / "autopara_launch.pyw").is_file()
        assert (installed / "requirements.txt").is_file()

    def test_removes_modules_the_new_version_dropped(self, source, installed):
        """The whole point: a leftover module is importable and beats nothing."""
        refresh.refresh_installation(installed)
        assert not (installed / "autopara" / "removed_module.py").exists()

    def test_does_not_carry_bytecode_across(self, source, installed):
        refresh.refresh_installation(installed)
        assert not (installed / "autopara" / "__pycache__").exists()

    def test_leaves_the_runtime_alone(self, source, installed):
        """Rebuilding the virtual environment on every run would cost minutes."""
        refresh.refresh_installation(installed)
        assert (installed / "runtime" / "python.exe").is_file()

    def test_a_frozen_build_refreshes_nothing(self, source, installed, monkeypatch):
        monkeypatch.setattr(refresh, "is_frozen", lambda: True)
        assert refresh.refresh_installation(installed) is None
        assert (installed / "autopara" / "app.py").read_text(encoding="utf-8") == "VERSION = 'old'\n"

    def test_refuses_to_copy_a_tree_that_is_not_autopara(self, tmp_path, installed, monkeypatch):
        empty = tmp_path / "not-autopara"
        empty.mkdir()
        monkeypatch.setattr(refresh, "source_root", lambda: empty)
        monkeypatch.setattr(refresh, "is_frozen", lambda: False)

        assert refresh.refresh_installation(installed) is None
        assert (installed / "autopara" / "app.py").is_file()

    def test_running_out_of_the_install_directory_is_a_no_op(self, source, monkeypatch):
        """Nothing to push when the source *is* the installation."""
        assert refresh.refresh_installation(source) is None

    def test_no_installation_means_nothing_to_do(self, source, monkeypatch):
        monkeypatch.setattr(refresh, "install_dir", lambda: None)
        assert refresh.refresh_installation() is None
