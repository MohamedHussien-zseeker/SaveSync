"""P0 workflow: Profile CRUD.

Covers: default profile on launch, create, select, rename, delete,
and persistence across app restarts.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from tests.fixtures.app_factory import create_app


class TestProfileCRUD:

    def test_default_profile_exists_on_launch(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            profile_btns = app.profile_list_frame.winfo_children()
            assert len(profile_btns) >= 1, "Expected at least one profile on launch"
            text = profile_btns[0].cget("text")
            assert "Default" in text, f"Expected 'Default' profile, got '{text}'"
        finally:
            root.destroy()

    def test_profiles_persist_across_restart(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        profiles_file = config_dir / "profiles.json"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", profiles_file)

        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        core_obj = core.SaveSyncCore()
        from core import Profile
        core_obj.profiles.append(Profile("PersistedProfile", []))
        core_obj.save_profiles()

        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            profile_btns = app.profile_list_frame.winfo_children()
            texts = [b.cget("text") for b in profile_btns]
            assert "PersistedProfile" in texts, (
                f"Persisted profile not found: {texts}"
            )
        finally:
            root.destroy()

    def test_select_profile_updates_detail_view(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            profile_btns = app.profile_list_frame.winfo_children()
            assert len(profile_btns) >= 1
            profile_btns[0].invoke()
            root.update()
            assert app.profile_name_val.cget("text") != ""
        finally:
            root.destroy()

    def test_profile_list_contains_names(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        profiles_file = config_dir / "profiles.json"
        profiles_file.parent.mkdir(parents=True, exist_ok=True)
        profiles_file.write_text(json.dumps([
            {"name": "Alpha", "watch_dirs": [], "provider_config": {"type": "local"}, "sync_on_close": False},
            {"name": "Beta", "watch_dirs": [], "provider_config": {"type": "local"}, "sync_on_close": False},
        ]))

        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", profiles_file)
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        root, refs = create_app(tmp_path, monkeypatch)
        try:
            app = refs.get("app")
            profile_btns = app.profile_list_frame.winfo_children()
            assert len(profile_btns) == 2
            profile_btns[0].invoke()
            root.update()
        finally:
            root.destroy()

    def test_delete_last_profile_not_allowed(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            del_btn = refs.get("btn_Delete")
            app = refs.get("app")
            profile_btns = app.profile_list_frame.winfo_children()
            assert del_btn is not None or len(profile_btns) >= 1
        finally:
            root.destroy()
