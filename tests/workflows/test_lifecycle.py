"""P1 workflow: Application lifecycle.

Covers: launch/quit, operation start/cancel/cleanup,
thread lifecycle, multiple launch cycles.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.fixtures.app_factory import create_app, find_button
from tests.helpers.assertions import assert_button_enabled


class TestLifecycle:

    def test_app_creates_and_destroys(self, tmp_path, monkeypatch):
        root, refs = create_app(tmp_path, monkeypatch)
        try:
            assert root is not None
            assert root.winfo_exists()
        finally:
            root.destroy()

    def test_backend_core_init(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        c = core.SaveSyncCore()
        assert len(c.profiles) >= 1
        assert c.profiles[0].name == "Default"

    def test_profile_persistence_core_only(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import Profile, SaveSyncCore
        c1 = SaveSyncCore()
        c1.profiles.append(Profile("LifecycleTest", []))
        c1.save_profiles()

        c2 = SaveSyncCore()
        names = [p.name for p in c2.profiles]
        assert "LifecycleTest" in names

    def test_sync_worker_lifecycle(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        src = tmp_path / "src"
        src.mkdir()
        (src / "game.sav").write_text("data")
        dest = tmp_path / "dest"
        dest.mkdir()

        c = SaveSyncCore()
        profile = Profile("WorkerLifecycle", [str(src)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        assert daemon.running is False
        daemon.start()
        assert daemon.running is True
        assert daemon._thread is not None
        assert daemon._thread.is_alive()

        daemon.stop()
        time.sleep(0.1)
        assert daemon.running is False
        if daemon._thread and daemon._thread.is_alive():
            daemon._thread.join(timeout=2)

    def test_sync_all_now_worker_cleanup(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        src = tmp_path / "src"
        src.mkdir()
        for i in range(10):
            (src / f"f{i}.sav").write_text("x" * 10000)
        dest = tmp_path / "dest"
        dest.mkdir()

        c = SaveSyncCore()
        profile = Profile("CleanupTest", [str(src)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        cancel = threading.Event()

        def cancel_soon():
            time.sleep(0.05)
            cancel.set()

        t = threading.Thread(target=cancel_soon, daemon=True)
        t.start()
        daemon.sync_all_now(cancel_event=cancel)
        t.join(timeout=3)

    def test_daemon_start_stop_idempotent(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        c = SaveSyncCore()
        profile = Profile("Idempotent", [str(src)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        daemon.start()
        daemon.start()
        assert daemon.running is True
        daemon.stop()
        daemon.stop()
        assert daemon.running is False

    def test_sync_completes_after_many_files(self, tmp_path, monkeypatch):
        fs = tmp_path / "src"
        fs.mkdir()
        for i in range(50):
            (fs / f"f{i:03d}.sav").write_text("sync_data_" + str(i) * 100)
        dest = tmp_path / "dest"
        dest.mkdir()

        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")
        import core
        core.ACCOUNTS_FILE = config_dir / "accounts.json"

        from core import SaveSyncCore, Profile, SaveSyncDaemon, OperationState
        c = SaveSyncCore()
        profile = Profile("ManyFiles", [str(fs)],
                          {"type": "local", "path": str(dest)})
        c.profiles = [profile]

        daemon = SaveSyncDaemon(c, profile)
        op_state = OperationState()
        daemon.sync_all_now(op_state=op_state)
        snap = op_state.snapshot()
        assert snap.files_completed == 50
        assert snap.phase == "Completed"
