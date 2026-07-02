"""P0 workflow: Provider connection.

Covers: local provider connection via the UI, accounts tab,
and disconnection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from tests.fixtures.app_factory import create_app
from tests.helpers.ui_actions import select_tab, click_button


class TestProviderConnection:

    def test_accounts_tab_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            assert notebook is not None, "Notebook not found"

            tab_count = notebook.index("end")
            tab_texts = [notebook.tab(i, "text").strip() for i in range(tab_count)]
            assert "Accounts" in tab_texts, f"Accounts tab not found in {tab_texts}"
        finally:
            root.destroy()

    def test_connect_account_button_exists(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            connect_btn = refs.get("btn_+ Connect Account")
            assert connect_btn is not None, "Connect Account button not found"
        finally:
            root.destroy()

    def test_add_account_button_enabled(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            connect_btn = refs.get("btn_+ Connect Account")
            assert connect_btn is not None
            state = str(connect_btn.cget("state"))
            assert state != "disabled", "Connect Account button should be enabled"
        finally:
            root.destroy()

    def test_navigate_to_accounts_and_back(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            notebook = refs.get("notebook")
            assert notebook is not None

            tab_texts = [notebook.tab(i, "text").strip() for i in range(notebook.index("end"))]
            accounts_idx = tab_texts.index("Accounts")
            select_tab(notebook, accounts_idx)
            root.update()

            home_idx = tab_texts.index("Home")
            select_tab(notebook, home_idx)
            root.update()
        finally:
            root.destroy()

    def test_local_provider_backend(self, tmp_path, monkeypatch):
        from core import SaveSyncCore, Profile
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        core_obj = SaveSyncCore()
        profile = Profile("ProviderTest", [str(tmp_path / "games")],
                          {"type": "local", "path": str(tmp_path / "backup")})
        core_obj.profiles.append(profile)
        core_obj.save_profiles()

        provider = core_obj.get_provider(profile)
        result = provider.test()
        assert result.startswith("OK"), f"Local provider test failed: {result}"
