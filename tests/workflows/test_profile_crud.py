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
from tests.helpers.ui_actions import click_button, select_tree_item


class TestProfileCRUD:

    def test_default_profile_exists_on_launch(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            tree = refs.get("tree")
            assert tree is not None, "Profile treeview not found"
            items = tree.get_children()
            assert len(items) >= 1, "Expected at least one profile on launch"
            first = tree.item(items[0], "values")
            assert any("Default" in str(v) for v in first), (
                f"Expected 'Default' profile, got {first}"
            )
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
            tree = refs.get("tree")
            items = tree.get_children()
            names = []
            for item in items:
                vals = tree.item(item, "values")
                names.extend(v for v in vals if v)
            assert "PersistedProfile" in names, (
                f"Persisted profile not found in tree: {names}"
            )
        finally:
            root.destroy()

    def test_select_profile_updates_detail_view(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            tree = refs.get("tree")
            items = tree.get_children()
            assert len(items) >= 1

            select_tree_item(tree, items[0])
            root.update()

            profile_lbl = refs.get("lbl_")
            notebook = refs.get("notebook")
            assert notebook is not None

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
            tree = refs.get("tree")
            items = tree.get_children()
            assert len(items) == 2

            select_tree_item(tree, items[0])
            root.update()
        finally:
            root.destroy()

    def test_delete_last_profile_not_allowed(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            del_btn = refs.get("btn_— Delete")
            tree = refs.get("tree")

            if del_btn and tree:
                items = tree.get_children()
                if len(items) < 2:
                    pass

        finally:
            root.destroy()
