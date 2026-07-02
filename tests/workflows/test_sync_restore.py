"""P0 workflow: Sync / Cancel / Restore.

Covers: sync now creates backup files, progress updates,
cancel during sync, restore brings back files, and
full sync/restore round-trip preserves data integrity.
"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from tests.fixtures.app_factory import create_app
from tests.fixtures.fake_filesystem import FakeFilesystem


class TestSyncRestore:

    def test_sync_creates_backup_files(self, tmp_path, monkeypatch):
        fs = FakeFilesystem(tmp_path / "src")
        fs.create_files(3)

        dest = tmp_path / "backup"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        c = SaveSyncCore()
        profile = Profile("SyncTest", [str(fs.root)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        daemon.sync_all_now()

        backed_up = list(dest.rglob("*"))
        assert len(backed_up) >= 3, f"Expected at least 3 backup files, got {len(backed_up)}"

    def test_sync_preserves_file_content(self, tmp_path, monkeypatch):
        fs = FakeFilesystem(tmp_path / "src")
        fs.create_file("game/save.dat", b"hello world")

        dest = tmp_path / "backup"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        c = SaveSyncCore()
        profile = Profile("ContentTest", [str(fs.root)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        daemon.sync_all_now()

        backed_up = (dest / "game" / "save.dat")
        assert backed_up.exists()
        assert backed_up.read_bytes() == b"hello world"

    def test_restore_round_trip(self, tmp_path, monkeypatch):
        fs = FakeFilesystem(tmp_path / "src")
        fs.create_file("original.sav", b"original data")

        dest = tmp_path / "backup"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from cloud import LocalFolder
        from core import SaveSyncCore, Profile, SaveSyncDaemon

        c = SaveSyncCore()
        profile = Profile("RoundTrip", [str(fs.root)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        daemon.sync_all_now()

        fs.modify_file("original.sav", b"modified data")

        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()

        restore_profile = Profile("Restore", [str(restore_dir)],
                                  {"type": "local", "path": str(dest)})
        restore_core = SaveSyncCore()
        restore_daemon = SaveSyncDaemon(restore_core, restore_profile)
        restore_daemon.provider = LocalFolder(str(dest))
        restore_daemon.restore_all(verify=False)

        restored = restore_dir / "original.sav"
        assert restored.exists(), "Restored file not found"
        assert restored.read_bytes() == b"original data", (
            "Restored content does not match original"
        )

    def test_cancel_stops_sync(self, tmp_path, monkeypatch):
        fs = FakeFilesystem(tmp_path / "src")
        for i in range(50):
            fs.create_file(f"bigfile_{i}.bin", b"x" * 50000)

        dest = tmp_path / "backup"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        c = SaveSyncCore()
        profile = Profile("CancelTest", [str(fs.root)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        cancel_event = threading.Event()

        def delayed_cancel():
            cancel_event.set()

        t = threading.Thread(target=delayed_cancel, daemon=True)
        t.start()
        daemon.sync_all_now(cancel_event=cancel_event)
        t.join(timeout=5)

        backed_up = len(list(dest.rglob("*")))
        assert backed_up < 50, (
            f"Cancel did not stop sync: {backed_up} files created (expected < 50)"
        )

    def test_op_state_tracks_progress(self, tmp_path, monkeypatch):
        fs = FakeFilesystem(tmp_path / "src")
        fs.create_files(10)

        dest = tmp_path / "backup"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        from state import OperationState

        c = SaveSyncCore()
        profile = Profile("ProgressTest", [str(fs.root)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        op_state = OperationState()
        daemon.sync_all_now(op_state=op_state)
        snap = op_state.snapshot()

        assert snap.files_completed == 10, f"Expected 10 files, got {snap.files_completed}"
        assert snap.phase == "Completed", f"Expected Completed, got {snap.phase}"
        assert snap.bytes_total > 0, "Expected bytes_total > 0"
