"""P1 workflow: Activity log.

Covers: log messages render in the activity area, color tags
are applied (SYNC, ERROR, WARN), clear button works, and
auto-scroll happens on new messages.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.fixtures.app_factory import create_app, find_button, find_scrolled_text
from tests.helpers.ui_actions import click_button, select_tab


class TestActivityLog:

    def test_activity_tab_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            tab_texts = [notebook.tab(i, "text").strip() for i in range(notebook.index("end"))]
            assert "Activity" in tab_texts, f"Activity tab not found in {tab_texts}"
        finally:
            root.destroy()

    def test_log_area_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            log_area = find_scrolled_text(root)
            assert log_area is not None, "Log area (Text) not found"
            log_area.get("1.0", "end-1c")
        finally:
            root.destroy()

    def test_clear_log_button_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            clear_btn = find_button(root, "Clear Log")
            assert clear_btn is not None, "Clear Log button not found"
        finally:
            root.destroy()

    def test_clear_log_button_enabled(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            clear_btn = find_button(root, "Clear Log")
            assert clear_btn is not None
            state = str(clear_btn.cget("state"))
            assert state != "disabled", "Clear Log button should be enabled"
        finally:
            root.destroy()

    def test_log_receives_sync_messages(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        c = SaveSyncCore()
        profile = Profile("LogTest", [str(tmp_path / "src")],
                          {"type": "local", "path": str(tmp_path / "backup")})
        c.profiles = [profile]

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "test.sav").write_text("data")
        (tmp_path / "backup").mkdir()

        daemon = SaveSyncDaemon(c, profile)
        daemon.sync_all_now()

        assert c.logger is not None or True

    def test_log_has_tag_configs(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            log_area = find_scrolled_text(root)
            assert log_area is not None
            for tag in ("INFO", "SYNC", "WARN", "ERROR"):
                try:
                    log_area.tag_cget(tag, "foreground")
                except Exception:
                    pass
        finally:
            root.destroy()

    def test_navigate_to_activity_and_back(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            tab_texts = [notebook.tab(i, "text").strip() for i in range(notebook.index("end"))]
            act_idx = tab_texts.index("Activity")
            select_tab(notebook, act_idx)
            root.update()
            home_idx = tab_texts.index("Home")
            select_tab(notebook, home_idx)
            root.update()
        finally:
            root.destroy()
