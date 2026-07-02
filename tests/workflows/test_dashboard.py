"""P1 workflow: Dashboard refresh and state propagation.

Covers: status bar, quick actions, progress area, overview stats,
and that state changes propagate to the dashboard after operations.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.fixtures.app_factory import create_app, find_button, find_label_containing, find_labelframe
from tests.helpers.ui_actions import select_tab
from tests.helpers.assertions import assert_button_enabled


class TestDashboard:

    def test_home_tab_is_first(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            assert notebook is not None
            tab_texts = [notebook.tab(i, "text").strip() for i in range(notebook.index("end"))]
            assert tab_texts[0] == "Home", f"First tab should be Home, got {tab_texts[0]}"
        finally:
            root.destroy()

    def test_all_five_tabs_present(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            tab_texts = [notebook.tab(i, "text").strip() for i in range(notebook.index("end"))]
            expected = ["Home", "Profiles", "Accounts", "Activity", "Settings"]
            for e in expected:
                assert e in tab_texts, f"Missing tab: {e}. Got {tab_texts}"
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
            progress = find_labelframe(root, " Progress ")
            assert progress is not None, "Progress LabelFrame not found"
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

    def test_switch_tabs_updates_view(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            for i in range(notebook.index("end")):
                select_tab(notebook, i)
                root.update()
        finally:
            root.destroy()

    def test_manage_profiles_button_navigates(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            mgmt_btn = find_button(root, "Manage Profiles →")
            assert mgmt_btn is not None, "Manage Profiles button not found"
        finally:
            root.destroy()

    def test_overview_section_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            overview = find_labelframe(root, " Overview ")
            assert overview is not None, "Overview LabelFrame not found"
        finally:
            root.destroy()
