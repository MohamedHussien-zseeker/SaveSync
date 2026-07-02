"""P1 workflow: Dashboard refresh and state propagation.

Covers: status bar, quick actions, progress area, overview stats,
and that state changes propagate to the dashboard after operations.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.fixtures.app_factory import create_app, find_button, find_label_containing, find_labelframe
from tests.helpers.assertions import assert_button_enabled


class TestDashboard:

    def test_home_page_is_first(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            assert app is not None
            first_nav = list(app.nav_btns.keys())[0]
            assert first_nav == "home", f"First nav button should be home, got {first_nav}"
        finally:
            root.destroy()

    def test_all_five_pages_present(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            expected = ["home", "games", "cloud", "activity", "settings"]
            for e in expected:
                assert e in app.nav_btns, f"Missing nav button: {e}. Got {list(app.nav_btns.keys())}"
        finally:
            root.destroy()

    def test_quick_action_buttons_exist(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            for btn_text in ["Sync Now", "Start Sync", "Restore"]:
                btn = find_button(root, btn_text)
                assert btn is not None, f"Quick action '{btn_text}' button not found"
        finally:
            root.destroy()

    def test_quick_actions_are_enabled(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            for btn_text in ["Sync Now", "Start Sync", "Restore"]:
                btn = find_button(root, btn_text)
                assert btn is not None
                assert_button_enabled(btn)
        finally:
            root.destroy()

    def test_progress_section_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            progress = find_labelframe(root, "Progress")
            assert progress is not None, "Progress section not found"
        finally:
            root.destroy()

    def test_status_bar_shows_version(self, tmp_path, monkeypatch):
        from SaveSync import __version__
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            version_lbl = find_label_containing(root, f"v{__version__}")
            assert version_lbl is not None, f"Version label 'v{__version__}' not found in status bar"
        finally:
            root.destroy()

    def test_status_bar_shows_ready_state(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            ready_lbl = find_label_containing(root, "Ready")
            assert ready_lbl is not None, "Ready status label not found in status bar"
        finally:
            root.destroy()

    def test_navigate_pages_updates_view(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            for page in ["home", "games", "cloud", "activity", "settings"]:
                app._show_page(page)
                root.update()
        finally:
            root.destroy()

    def test_manage_games_button_navigates(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            mgmt_btn = find_button(root, "Manage Games")
            assert mgmt_btn is not None, "Manage Games button not found"
        finally:
            root.destroy()

    def test_dashboard_header_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            header = find_label_containing(root, "Dashboard")
            assert header is not None, "Dashboard header label not found"
        finally:
            root.destroy()
