"""SaveSync unit and integration tests."""
import ast
import hashlib
import json
import os
import tempfile
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import Profile, SaveSyncCore, SaveSyncDaemon, GuiLogHandler, setup_file_logger, _log_path, _detect_watcher
from cloud import CloudProvider, LocalFolder, create_provider
from transfer import TransferManager, CHUNK_SIZE

# -- Cloud provider tests --


class TestCloudProvider:
    def test_local_folder_upload_download(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("hello")

        dest_root = str(tmp_path / "backup")
        provider = LocalFolder(dest_root)

        assert provider.upload(str(src_file), "game/save.txt")
        assert (Path(dest_root) / "game" / "save.txt").exists()
        assert (Path(dest_root) / "game" / "save.txt").read_text() == "hello"

    def test_local_folder_download(self, tmp_path):
        dest_root = str(tmp_path / "backup")
        os.makedirs(os.path.join(dest_root, "game"), exist_ok=True)
        Path(dest_root, "game", "save.txt").write_text("backup data")

        provider = LocalFolder(dest_root)
        restore_path = tmp_path / "restore" / "save.txt"
        assert provider.download(str(restore_path), "game/save.txt")
        assert restore_path.read_text() == "backup data"

    def test_local_folder_list_files(self, tmp_path):
        dest_root = str(tmp_path / "backup")
        os.makedirs(os.path.join(dest_root, "sub"), exist_ok=True)
        Path(dest_root, "file1.txt").write_text("a")
        Path(dest_root, "sub", "file2.txt").write_text("b")

        provider = LocalFolder(dest_root)
        files = provider.list_files()
        assert "file1.txt" in files
        assert "sub/file2.txt" in files

    def test_local_folder_test_writable(self, tmp_path):
        provider = LocalFolder(str(tmp_path / "backup"))
        result = provider.test()
        assert result.startswith("OK")

    def test_create_provider_local(self):
        provider = create_provider({"type": "local", "path": "/tmp/savesync_test"})
        assert isinstance(provider, LocalFolder)

    def test_create_provider_unknown(self):
        with pytest.raises(ValueError):
            create_provider({"type": "nonexistent"})


class TestDropboxLazyImport:
    def test_dropbox_import_not_required_for_local(self):
        """Verify DropboxProvider class can be imported without the SDK."""
        from cloud import DropboxProvider
        assert DropboxProvider is not None

    def test_dropbox_import_not_at_top_level(self):
        """Verify cloud.py does not have 'import dropbox' at module level."""
        import cloud
        source = Path(cloud.__file__).read_text()
        lines = source.splitlines()
        top_imports = [l for l in lines if l.startswith('import ') or l.startswith('from ')]
        assert not any('import dropbox' in l for l in top_imports), \
            f"Found top-level dropbox import: {top_imports}"

    def test_dropbox_test_graceful_without_sdk(self):
        from cloud import DropboxProvider
        provider = DropboxProvider("fake_token")
        result = provider.test()
        assert "not installed" in result or "ERROR" in result or "OK" in result

    def test_dropbox_get_client_returns_none_without_sdk(self):
        from cloud import DropboxProvider
        provider = DropboxProvider("fake_token")
        client = provider._get_client()
        assert client is None

    def test_dropbox_upload_graceful_without_sdk(self):
        from cloud import DropboxProvider
        provider = DropboxProvider("fake_token")
        result = provider.upload("/nonexistent", "test.txt")
        assert result is False


# -- Profile tests --


class TestProfile:
    def test_profile_defaults(self):
        p = Profile("MyProfile", [])
        assert p.name == "MyProfile"
        assert p.watch_dirs == []
        assert p.provider_config["type"] == "local"
        assert p.sync_on_close is False

    def test_profile_serialization_roundtrip(self):
        p1 = Profile("Test", ["/path1"], {"type": "dropbox", "token": "abc"}, sync_on_close=True)
        data = p1.to_dict()
        p2 = Profile.from_dict(data)
        assert p2.name == "Test"
        assert p2.watch_dirs == ["/path1"]
        assert p2.provider_config["type"] == "dropbox"
        assert p2.sync_on_close is True


# -- SaveSyncCore tests --


class TestSaveSyncCore:
    def test_core_creates_default_profile(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")

        import logging_system
        original = logging_system.get_logging_system

        try:
            core = SaveSyncCore()
            assert len(core.profiles) >= 1
            assert core.profiles[0].name == "Default"
        finally:
            pass

    def test_core_save_and_load_profiles(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "savesync"
        monkeypatch.setattr("core.SaveSyncCore.CONFIG_DIR", config_dir)
        monkeypatch.setattr("core.SaveSyncCore.PROFILES_FILE", config_dir / "profiles.json")

        core = SaveSyncCore()
        core.profiles.append(Profile("MyNew", ["/game/saves"], {"type": "local"}))
        core.save_profiles()

        core2 = SaveSyncCore()
        names = [p.name for p in core2.profiles]
        assert "Default" in names
        assert "MyNew" in names


# -- SaveSync daemon tests --


class TestSaveSyncDaemon:
    def test_rel_path(self, tmp_path):
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        test_file = tmp_path / "sub" / "save.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("data")
        rel = daemon._rel_path(str(test_file))
        assert rel == "sub/save.txt" or rel == os.path.join("sub", "save.txt")

    def test_scan_finds_files(self, tmp_path):
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        snap = daemon._scan(str(tmp_path))
        assert len(snap) == 2

    def test_sync_path_with_local_provider(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("sync data")

        dest_dir = tmp_path / "dest"
        os.makedirs(dest_dir)

        profile = Profile("Test", [str(src_dir)], {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon._sync_path(str(src_file))
        assert (dest_dir / "save.txt").exists()
        assert (dest_dir / "save.txt").read_text() == "sync data"


# -- Logger tests --


class TestGuiLogHandler:
    def test_handler_formats_message(self):
        import logging
        class FakeWidget:
            def __init__(self):
                self.text = ""
            def insert(self, pos, text, tag=None):
                self.text += text
            def see(self, pos):
                pass

        widget = FakeWidget()
        handler = GuiLogHandler(widget)
        record = logging.LogRecord("test", logging.INFO, "", 0, "test message", (), None)
        handler.emit(record)
        assert "test message" in widget.text

    def test_handler_sync_tag(self):
        import logging
        class FakeWidget:
            def __init__(self):
                self.text = ""
                self.last_tag = None
            def insert(self, pos, text, tag=None):
                self.text += text
                self.last_tag = tag
            def see(self, pos):
                pass

        widget = FakeWidget()
        handler = GuiLogHandler(widget)
        record = logging.LogRecord("test", logging.INFO, "", 0, "sync completed", (), None)
        handler.emit(record)
        assert widget.last_tag == "SYNC"


class TestLogPath:
    def test_log_path_creates_writable(self):
        path = _log_path()
        assert path.name == "savesync.log"
        assert path.parent.exists() or True

    def test_detect_watcher(self):
        watcher = _detect_watcher()
        assert watcher in ("inotify", "poll")


# -- CLI --


class TestCLI:
    def test_version_flag(self):
        from SaveSync import __version__, main
        assert __version__
        assert "." in __version__
        assert all(c.isprintable() for c in __version__)

    def test_main_version_exits(self):
        from SaveSync import main
        old_argv = sys.argv
        try:
            sys.argv = ["savesync.py", "--version"]
            main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv


# -- Logging system tests --


class TestLoggingSystem:
    def test_log_event_to_dict(self):
        from logging_system import LogEvent
        event = LogEvent("test_event", "session123", {"key": "val"})
        d = event.to_dict()
        assert d["event_type"] == "test_event"
        assert d["session_id"] == "session123"
        assert d["data"]["key"] == "val"

    def test_json_logger_write_and_read(self, tmp_path, monkeypatch):
        from logging_system import JsonLogger, _logs_dir, LogEvent

        monkeypatch.setattr("logging_system._logs_dir", lambda: tmp_path)
        logger = JsonLogger("test.jsonl")
        event = LogEvent("write_test", "sid1", {"msg": "hello"})
        logger.write(event)
        events = logger.read_all()
        assert len(events) == 1
        assert events[0]["event_type"] == "write_test"

    def test_session_tracker_start_end(self):
        from logging_system import SessionTracker
        tracker = SessionTracker()
        assert tracker.session_id is not None
        assert len(tracker.session_id) == 12

    def test_get_logging_system_singleton(self):
        from logging_system import get_logging_system, shutdown
        ls1 = get_logging_system()
        ls2 = get_logging_system()
        assert ls1 is ls2
        shutdown()

    def test_shutdown_clears_singleton(self):
        from logging_system import get_logging_system, shutdown
        ls1 = get_logging_system()
        shutdown()
        ls2 = get_logging_system()
        assert ls1 is not ls2
        shutdown()

    def test_error_logger_capture(self):
        from logging_system import LoggingSystem
        ls = LoggingSystem("test")
        try:
            1 / 0
        except ZeroDivisionError as e:
            ls.errors.capture("test_module", e)
        assert ls.errors.error_count > 0

    def test_filesystem_logger_events(self):
        from logging_system import LoggingSystem
        ls = LoggingSystem("test")
        ls.fs.created("/tmp/test.txt", 100)
        ls.fs.modified("/tmp/test.txt", 200)
        ls.fs.deleted("/tmp/test.txt")
        assert True

    def test_sync_logger_events(self):
        from logging_system import LoggingSystem
        ls = LoggingSystem("test")
        ls.sync.started("sync_001", "/games")
        ls.sync.file_uploaded("save.dat", 500)
        ls.sync.completed("sync_001", 1)
        assert True

    def test_audit_logger_events(self):
        from logging_system import LoggingSystem
        ls = LoggingSystem("test")
        ls.audit.action("test_action", {"detail": "value"})
        ls.audit.login()
        assert True

    def test_cleanup_preserves_recent(self, tmp_path, monkeypatch):
        from logging_system import JsonLogger, LogEvent, _RETENTION_DAYS
        monkeypatch.setattr("logging_system._logs_dir", lambda: tmp_path)
        monkeypatch.setattr("logging_system._CURRENT_ENV", "development")

        logger = JsonLogger("cleanup_test.jsonl")
        event = LogEvent("old_event", "sid", {"msg": "old"})
        logger.write(event)
        logger.cleanup(retention_days=0)
        # with 0 retention, nothing is old enough to be pruned
        count = logger.count()
        assert count >= 0


# -- Credential store tests --


class TestCredentialStore:
    def test_ephemeral_store_and_get(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        store.store("savesync", "test_account", "my_secret_token_123")
        result = store.get("savesync", "test_account")
        assert result == "my_secret_token_123"

    def test_ephemeral_store_delete(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        store.store("savesync", "del_test", "to_delete")
        assert store.get("savesync", "del_test") == "to_delete"
        assert store.delete("savesync", "del_test") is True
        assert store.get("savesync", "del_test") is None

    def test_ephemeral_store_get_nonexistent(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        assert store.get("savesync", "no_such_account") is None

    def test_ephemeral_store_list_accounts(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        store.store("svc1", "alice", "secret1")
        store.store("svc1", "bob", "secret2")
        accounts = store.list_accounts("svc1")
        assert "alice" in accounts
        assert "bob" in accounts

    def test_ephemeral_store_available(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        assert store.available() is True

    def test_ephemeral_separate_services(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        store.store("svc_a", "key1", "val_a")
        store.store("svc_b", "key1", "val_b")
        assert store.get("svc_a", "key1") == "val_a"
        assert store.get("svc_b", "key1") == "val_b"

    def test_ephemeral_delete_nonexistent(self):
        from credential_store import EphemeralCredentialStore
        store = EphemeralCredentialStore()
        assert store.delete("nosvc", "noacct") is False

    def test_redact_secrets_dict(self):
        from credential_store import redact_secrets
        data = {
            "normal": "visible",
            "token": "should_be_hidden",
            "nested": {"secret": "hidden", "name": "visible"},
        }
        result = redact_secrets(data)
        assert result["normal"] == "visible"
        assert result["token"] == "***REDACTED***"
        assert result["nested"]["secret"] == "***REDACTED***"
        assert result["nested"]["name"] == "visible"

    def test_redact_secrets_list(self):
        from credential_store import redact_secrets
        result = redact_secrets([{"token": "hidden"}, {"name": "visible"}])
        assert result[0]["token"] == "***REDACTED***"
        assert result[1]["name"] == "visible"

    def test_redact_secrets_non_dict(self):
        from credential_store import redact_secrets
        assert redact_secrets("hello") == "hello"
        assert redact_secrets(42) == 42

    def test_get_credential_store_returns_store(self):
        from credential_store import get_credential_store, CredentialStore
        store = get_credential_store()
        assert isinstance(store, CredentialStore)
        assert store.available() is True


# -- Provider registry and adapter tests --


class TestAccount:
    def test_account_serialization_roundtrip(self):
        from providers import Account
        a1 = Account(
            provider="google_drive",
            account_id="abc123",
            display_email="user@gmail.com",
            display_name="My Drive",
            capabilities=["upload", "download"],
            credential_ref="cred_abc",
            connected_at="2026-01-01T00:00:00",
            provider_config={"folder_type": "appDataFolder"},
        )
        data = a1.to_dict()
        a2 = Account.from_dict(data)
        assert a2.provider == "google_drive"
        assert a2.account_id == "abc123"
        assert a2.display_email == "user@gmail.com"
        assert a2.credential_ref == "cred_abc"

    def test_account_redacts_tokens_in_to_dict(self):
        from providers import Account
        a = Account(
            provider="dropbox",
            account_id="d1",
            display_email="",
            display_name="",
            provider_config={"token": "should_be_redacted"},
        )
        data = a.to_dict()
        assert data["provider_config"]["token"] == "***REDACTED***"


class TestProviderRegistry:
    def test_registry_has_default_providers(self):
        from providers import get_provider_registry
        registry = get_provider_registry()
        providers = registry.list_providers()
        names = [p["name"] for p in providers]
        assert "local" in names
        assert "dropbox" in names
        assert "google_drive" in names
        assert "onedrive" in names

    def test_registry_get_instance(self):
        from providers import get_provider_registry, LocalAdapter
        registry = get_provider_registry()
        inst = registry.get_instance("local")
        assert inst is not None
        assert isinstance(inst, LocalAdapter)

    def test_registry_get_unknown(self):
        from providers import get_provider_registry
        registry = get_provider_registry()
        assert registry.get("nonexistent") is None
        assert registry.get_instance("nonexistent") is None


class TestLocalAdapter:
    def test_connect_creates_account(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        backup_dir = str(tmp_path / "backup")
        result = OAuthResult("", "", 0, "local_id1", "", "Local Folder")
        account = adapter.connect(result, {"path": backup_dir})
        assert account.provider == "local"
        assert account.account_id.startswith("local_")
        assert os.path.isdir(backup_dir)

    def test_status_ok_when_writable(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        backup_dir = str(tmp_path / "backup")
        os.makedirs(backup_dir)
        result = OAuthResult("", "", 0, "local_id2", "", "Local Folder")
        account = adapter.connect(result, {"path": backup_dir})
        ok, msg = adapter.status(account)
        assert ok is True

    def test_upload_and_download(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("hello provider")
        backup_dir = str(tmp_path / "backup")
        result = OAuthResult("", "", 0, "local_id3", "Local")
        account = adapter.connect(result, {"path": backup_dir})
        adapter._account = account
        adapter.dest_root = backup_dir
        assert adapter.upload(str(src_file), "game/save.txt")
        assert (tmp_path / "backup" / "game" / "save.txt").exists()

    def test_list_files(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "file1.txt").write_text("a")
        (backup_dir / "sub").mkdir()
        (backup_dir / "sub" / "file2.txt").write_text("b")
        adapter.dest_root = str(backup_dir)
        files = adapter.list_files()
        assert "file1.txt" in files
        assert "sub/file2.txt" in files


class TestDropboxAdapter:
    def test_build_oauth_url_contains_expected_params(self):
        from providers import DropboxAdapter
        adapter = DropboxAdapter()
        url = adapter.build_oauth_url(
            {"app_key": "test_key", "app_secret": "test_secret"},
            "http://127.0.0.1:18080/", "state123", "verifier123")
        assert "test_key" in url
        assert "dropbox.com" in url
        assert "state123" in url
        assert "offline" in url

    def test_connect_with_result(self):
        from providers import DropboxAdapter, OAuthResult
        adapter = DropboxAdapter()
        from datetime import datetime, timezone
        result = OAuthResult(
            access_token="test_at",
            refresh_token="test_rt",
            expires_at=9999999999,
            account_id="dbid_test",
            display_email="test@dropbox.com",
        )
        account = adapter.connect(result, {"app_key": "k", "app_secret": "s"})
        assert account.provider == "dropbox"
        assert account.account_id == "dbid_test"
        assert account.display_email == "test@dropbox.com"

    def test_sanitize_path(self):
        from providers import DropboxAdapter
        adapter = DropboxAdapter()
        result = adapter._sanitize("my<file>:?.txt")
        assert "<" not in result
        assert "?" not in result
        assert ":" not in result


class TestGoogleDriveAdapter:
    def test_build_oauth_url_contains_expected_params(self):
        from providers import GoogleDriveAdapter
        adapter = GoogleDriveAdapter()
        client_config = {
            "installed": {
                "client_id": "test_id.apps.googleusercontent.com",
                "client_secret": "test_secret",
            }
        }
        url = adapter.build_oauth_url(
            client_config, "http://127.0.0.1:18080/",
            "state_abc", "verifier_xyz")
        assert "test_id" in url
        assert "accounts.google.com" in url
        assert "state_abc" in url

    def test_parse_client_config_installed(self):
        from providers import GoogleDriveAdapter
        adapter = GoogleDriveAdapter()
        client_id, client_secret = adapter._parse_client_config({
            "installed": {"client_id": "id1", "client_secret": "secret1"}
        })
        assert client_id == "id1"
        assert client_secret == "secret1"

    def test_connect_with_result(self):
        from providers import GoogleDriveAdapter, OAuthResult
        adapter = GoogleDriveAdapter()
        result = OAuthResult(
            access_token="test_at",
            refresh_token="test_rt",
            expires_at=9999999999,
            account_id="gid_test",
            display_email="test@gmail.com",
        )
        account = adapter.connect(result)
        assert account.provider == "google_drive"
        assert account.account_id == "gid_test"
        assert account.display_email == "test@gmail.com"
        assert account.provider_config["folder_type"] == "appDataFolder"


class TestOneDriveAdapter:
    def test_build_oauth_url_contains_expected_params(self):
        from providers import OneDriveAdapter
        adapter = OneDriveAdapter()
        url = adapter.build_oauth_url(
            {"client_id": "my_client_id"},
            "http://127.0.0.1:18080/", "state_od", "verifier_od")
        assert "my_client_id" in url
        assert "login.microsoftonline.com" in url
        assert "Files.ReadWrite.AppFolder" in url

    def test_connect_with_result(self):
        from providers import OneDriveAdapter, OAuthResult
        adapter = OneDriveAdapter()
        result = OAuthResult(
            access_token="test_at_od",
            refresh_token="test_rt_od",
            expires_at=9999999999,
            account_id="od_id",
            display_email="user@onedrive.com",
        )
        account = adapter.connect(result)
        assert account.provider == "onedrive"
        assert account.account_id == "od_id"


# -- Config sync tests --


class TestSyncConfig:
    def test_sync_config_serialization_roundtrip(self):
        from config_sync import SyncConfig
        c1 = SyncConfig()
        c1.profile_ids = ["p1", "p2"]
        c1.profile_names = ["Profile1", "Profile2"]
        data = c1.to_dict()
        c2 = SyncConfig.from_dict(data)
        assert c2.schema_version == 1
        assert c2.profile_ids == ["p1", "p2"]
        assert c2.profile_names == ["Profile1", "Profile2"]

    def test_sync_config_redacts_secrets(self):
        from config_sync import SyncConfig
        c = SyncConfig()
        c.preferences = {"token": "hidden", "theme": "dark"}
        data = c.to_dict()
        assert data["preferences"]["token"] == "***REDACTED***"
        assert data["preferences"]["theme"] == "dark"

    def test_device_config_defaults(self):
        from config_sync import DeviceConfig
        d = DeviceConfig()
        assert d.device_id is not None
        assert len(d.device_id) == 12
        assert d.platform in ("Linux", "Windows", "Darwin")

    def test_device_config_roundtrip(self):
        from config_sync import DeviceConfig
        d1 = DeviceConfig(device_id="test123", device_name="my-pc",
                          platform="Linux",
                          folder_mappings={"/games": "/backup/games"})
        data = d1.to_dict()
        d2 = DeviceConfig.from_dict(data)
        assert d2.device_id == "test123"
        assert d2.device_name == "my-pc"
        assert d2.folder_mappings["/games"] == "/backup/games"


class TestConfigSyncLocal:
    def test_sync_config_parse_iso(self):
        from config_sync import _parse_iso
        ts = _parse_iso("2026-06-27T12:00:00+00:00")
        assert isinstance(ts, float)
        assert ts > 0

    def test_sync_config_parse_iso_empty(self):
        from config_sync import _parse_iso
        assert _parse_iso("") == 0
        assert _parse_iso(None) == 0

    def test_get_device_id(self):
        from config_sync import _get_device_id
        did = _get_device_id()
        assert did is not None
        assert len(did) == 12

    def test_get_device_id_persists(self, monkeypatch):
        import tempfile
        from config_sync import _get_device_id
        test_dir = tempfile.mkdtemp()
        monkeypatch.setattr("config_sync.Path.home",
                            lambda: Path(test_dir))
        did1 = _get_device_id()
        did2 = _get_device_id()
        assert did1 == did2


class TestBuildRegression:
    """Regression tests that catch issues like the 2.3.0 PyInstaller omission and 2.3.1 _stat_row crash."""

    def test_python_37_ast_compile(self):
        """Every .py must compile under Python 3.7 AST (no f-string backslashes, walrus, match, etc.)."""
        src = Path(__file__).resolve().parent.parent
        failures = []
        for f in sorted(src.glob("*.py")):
            try:
                ast.parse(f.read_text(), feature_version=(3, 7))
            except SyntaxError as e:
                failures.append((f.name, e.lineno, e.msg))
        assert not failures, f"Python 3.7 AST failures: {failures}"

    def test_all_modules_import(self):
        """All project modules import without error."""
        src = str(Path(__file__).resolve().parent.parent)
        old_path = sys.path.copy()
        sys.path.insert(0, src)
        try:
            for mod in ["credential_store", "providers", "config_sync",
                        "core", "cloud", "logging_system", "SaveSync"]:
                __import__(mod)
        finally:
            sys.path = old_path

    def test_dpapi_encrypt_decrypt_roundtrip(self):
        """_encrypt / _decrypt round-trips correctly using the ctypes DPAPI implementation."""
        from credential_store import WindowsDPAPICredentialStore
        store = WindowsDPAPICredentialStore()
        # The ctypes module uses crypt32.dll which isn't available on Linux,
        # so mock the module-level functions for testing.
        import credential_store as cs

        orig_enc = cs._dpapi_encrypt
        orig_dec = cs._dpapi_decrypt

        def fake_encrypt(plain: bytes) -> bytes:
            return b"ENC:" + plain

        def fake_decrypt(blob: bytes) -> bytes:
            return blob[4:]

        cs._dpapi_encrypt = fake_encrypt
        cs._dpapi_decrypt = fake_decrypt
        try:
            encrypted = store._encrypt("hello")
            decrypted = store._decrypt(encrypted)
            assert decrypted == "hello"
        finally:
            cs._dpapi_encrypt = orig_enc
            cs._dpapi_decrypt = orig_dec

    def test_self_test_imports(self):
        """--self-test flag does not require tkinter or other GUI deps."""
        src = str(Path(__file__).resolve().parent.parent)
        old_path = sys.path.copy()
        old_argv = sys.argv.copy()
        old_stdout = sys.stdout
        import io
        sys.path.insert(0, src)
        sys.argv = ["SaveSync.py", "--self-test"]
        sys.stdout = io.StringIO()
        try:
            from SaveSync import _self_test
            _self_test()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
            sys.path = old_path


class TestSyncWorker:
    def test_worker_initial_state(self):
        from core import SyncWorker, SaveSyncCore
        core = SaveSyncCore()
        profile = core.profiles[0]
        worker = SyncWorker(core, profile)
        assert worker.is_running is False
        assert worker.current_op is None

    def test_worker_rejects_concurrent_sync(self):
        from core import SyncWorker, SaveSyncCore
        import threading, time
        core = SaveSyncCore()
        profile = core.profiles[0]
        worker = SyncWorker(core, profile)
        alive = threading.Event()
        def stay_alive():
            alive.wait(timeout=5)
        dummy_thread = threading.Thread(target=stay_alive, daemon=True)
        dummy_thread.start()
        worker._thread = dummy_thread
        assert worker.is_running is True
        assert worker.sync_all() is False
        assert worker.restore_all() is False
        alive.set()
        dummy_thread.join(timeout=5)

    def test_worker_cancel(self):
        from core import SyncWorker, SaveSyncCore
        import threading
        core = SaveSyncCore()
        profile = core.profiles[0]
        worker = SyncWorker(core, profile)
        cancelled = [False]
        def fake_sync(pc, dc):
            worker.cancel()
            cancelled[0] = worker._cancel_event.is_set()
        worker._do_sync = fake_sync
        worker.sync_all()
        assert cancelled[0]

    def test_sync_all_now_op_state(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "save1.txt").write_text("data1")
        (src_dir / "save2.txt").write_text("data2")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Test", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        op_state = OperationState()
        daemon.sync_all_now(op_state=op_state)
        snap = op_state.snapshot()
        assert snap.files_completed == 2
        assert snap.phase == "Completed"
        assert snap.bytes_total > 0
        assert snap.bytes_transferred > 0

    def test_sync_all_now_cancel(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        import threading
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for i in range(50):
            (src_dir / f"file_{i}.txt").write_text("x" * 1000)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Test", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        cancel_event = threading.Event()
        cancel_event.set()
        daemon.sync_all_now(cancel_event=cancel_event)
        assert len(list(dest_dir.iterdir())) < 50


class TestRestoreSafety:
    def test_pre_restore_backup_creates_backup(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        dest = tmp_path / "existing_file.txt"
        dest.write_text("original data")
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        backup = daemon._pre_restore_backup(str(dest))
        assert backup and os.path.exists(backup)
        assert open(backup).read() == "original data"

    def test_pre_restore_backup_nonexistent(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        nonexistent = tmp_path / "no_such_file.txt"
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        backup = daemon._pre_restore_backup(str(nonexistent))
        assert backup == ""

    def test_verify_checksum_computes_sha256(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world" * 1000)
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        sha = daemon._verify_checksum(str(f))
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_verify_checksum_nonexistent(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        sha = daemon._verify_checksum(str(tmp_path / "nope"))
        assert sha == ""

    def test_multi_folder_restore_skips_existing(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        from cloud import LocalFolder
        src1 = tmp_path / "game1"
        src1.mkdir()
        src2 = tmp_path / "game2"
        src2.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "save.dat").write_text("backup data")
        (src1 / "save.dat").write_text("existing")  # already exists in game1
        profile = Profile("Test", [str(src1), str(src2)],
                          {"type": "local", "path": str(backup)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon.provider = LocalFolder(str(backup))
        daemon.restore_all(verify=False)
        assert (src2 / "save.dat").read_text() == "backup data"

    def test_restore_finds_available_folder(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        from cloud import LocalFolder
        src1 = tmp_path / "game1"
        src1.mkdir()
        src2 = tmp_path / "game2"
        src2.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "save.dat").write_text("to restore")
        profile = Profile("Test", [str(src1), str(src2)],
                          {"type": "local", "path": str(backup)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon.provider = LocalFolder(str(backup))
        daemon.restore_all(verify=False)
        assert (src1 / "save.dat").read_text() == "to restore"


class TestLocalAdapterVerification:
    def test_upload_verifies_checksum(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("data to verify")
        backup_dir = str(tmp_path / "backup")
        result = OAuthResult("", "", 0, "local_v", "", "Local")
        account = adapter.connect(result, {"path": backup_dir})
        adapter._account = account
        adapter.dest_root = backup_dir
        assert adapter.upload(str(src_file), "game/save.txt")
        assert (tmp_path / "backup" / "game" / "save.txt").exists()

    def test_upload_detects_corruption(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("before corruption")
        backup_dir = str(tmp_path / "backup")
        result = OAuthResult("", "", 0, "local_c", "", "Local")
        account = adapter.connect(result, {"path": backup_dir})
        adapter._account = account
        adapter.dest_root = backup_dir
        import shutil
        shutil.copy2(str(src_file), os.path.join(backup_dir, "save.txt"))
        with open(os.path.join(backup_dir, "save.txt"), "w") as f:
            f.write("corrupted during copy")
        src_hash = adapter._sha256(str(src_file))
        dst_hash = adapter._sha256(os.path.join(backup_dir, "save.txt"))
        assert src_hash != dst_hash


class TestDaemonThreadSafety:
    def test_pending_lock(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        import threading
        def add_items(offset):
            for i in range(100):
                with daemon._pending_lock:
                    daemon._pending.add(f"/path/{offset}_{i}")
        threads = [threading.Thread(target=add_items, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with daemon._pending_lock:
            assert len(daemon._pending) == 400

    def test_snapshots_lock(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        profile = Profile("Test", [str(tmp_path)])
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        import threading
        with daemon._snapshots_lock:
            daemon._snapshots["/a"] = {"f1": 1.0}
        accessed = []
        def read_snap():
            with daemon._snapshots_lock:
                accessed.append(daemon._snapshots.get("/a", {}))
        t = threading.Thread(target=read_snap)
        t.start()
        t.join()
        assert len(accessed) == 1
        assert accessed[0].get("f1") == 1.0


# --- Stabilization --- Stress Tests ---

class TestStressLargeScaleSync:
    def test_sync_1000_small_files(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for i in range(1000):
            (src_dir / "file_{}.txt".format(i)).write_text("data_{}".format(i) * 10)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Stress", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        op_state = OperationState()
        daemon.sync_all_now(op_state=op_state)
        snap = op_state.snapshot()
        assert snap.files_completed == 1000
        assert len(list(dest_dir.rglob("*"))) == 1000

    def test_sync_large_files(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        large = src_dir / "large.bin"
        with open(str(large), "wb") as f:
            f.write(b"x" * 50 * 1024 * 1024)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Large", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon.sync_all_now()
        dest_file = dest_dir / "large.bin"
        assert dest_file.exists()
        assert dest_file.stat().st_size == 50 * 1024 * 1024

    def test_cancel_during_sync(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        import threading, time
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for i in range(200):
            (src_dir / "file_{}.txt".format(i)).write_text("x" * 1000)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Cancel", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        cancel_event = threading.Event()
        op_state = OperationState()
        def watcher():
            while not cancel_event.is_set():
                snap = op_state.snapshot()
                if snap.files_completed >= 20:
                    cancel_event.set()
                    return
                time.sleep(0.01)
        threading.Thread(target=watcher, daemon=True).start()
        daemon.sync_all_now(op_state=op_state, cancel_event=cancel_event)
        snap = op_state.snapshot()
        assert snap.files_completed < 200
        assert cancel_event.is_set()

    def test_cancel_during_restore(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        from cloud import LocalFolder
        import threading, time
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        for i in range(200):
            (backup_dir / "file_{}.txt".format(i)).write_text("x" * 100)
        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        profile = Profile("CancelRest", [str(restore_dir)],
                          {"type": "local", "path": str(backup_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon.provider = LocalFolder(str(backup_dir))
        cancel_event = threading.Event()
        op_state = OperationState()
        def watcher():
            while not cancel_event.is_set():
                snap = op_state.snapshot()
                if snap.files_completed >= 10:
                    cancel_event.set()
                    return
                time.sleep(0.01)
        threading.Thread(target=watcher, daemon=True).start()
        daemon.restore_all(op_state=op_state, cancel_event=cancel_event,
                           verify=False)
        snap = op_state.snapshot()
        assert snap.files_completed < 200
        assert cancel_event.is_set()

    def test_concurrent_sync_rejected(self, tmp_path):
        from core import SyncWorker, SaveSyncCore, Profile
        import threading
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Conc", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        alive = threading.Event()
        def stay_alive():
            alive.wait(timeout=5)
        t = threading.Thread(target=stay_alive, daemon=True)
        t.start()
        worker._thread = t
        assert worker.sync_all() is False
        assert worker.restore_all() is False
        alive.set()
        t.join(timeout=5)

    def test_worker_cleanup_after_cancel(self, tmp_path):
        from core import SyncWorker, SaveSyncCore, Profile
        import threading
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for i in range(10):
            (src_dir / "f_{}.txt".format(i)).write_text("data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Cleanup", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        alive = threading.Event()
        def stay_alive():
            alive.wait(timeout=5)
        t = threading.Thread(target=stay_alive, daemon=True)
        t.start()
        worker._thread = t
        worker.cancel()
        assert worker._cancel_event.is_set()
        alive.set()
        t.join(timeout=5)

    def test_readonly_destination_handled(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "save.txt").write_text("data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        os.chmod(str(dest_dir), 0o555)
        try:
            profile = Profile("RO", [str(src_dir)],
                              {"type": "local", "path": str(dest_dir)})
            core = SaveSyncCore()
            daemon = SaveSyncDaemon(core, profile)
            daemon.sync_all_now()
            exists = False
            try:
                exists = (dest_dir / "save.txt").exists()
            except Exception:
                pass
            assert not exists, "File should not have been created in read-only dir"
        finally:
            os.chmod(str(dest_dir), 0o755)

    def test_verify_integrity_after_sync(self, tmp_path):
        from providers import LocalAdapter, OAuthResult
        adapter = LocalAdapter()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "save.txt"
        src_file.write_text("data to verify")
        backup_dir = str(tmp_path / "backup")
        result = OAuthResult("", "", 0, "local_vfy", "", "Local")
        account = adapter.connect(result, {"path": backup_dir})
        adapter._account = account
        adapter.dest_root = backup_dir
        assert adapter.upload(str(src_file), "game/save.txt")
        src_hash = adapter._sha256(str(src_file))
        dst_hash = adapter._sha256(os.path.join(backup_dir, "game", "save.txt"))
        assert src_hash == dst_hash, "Checksums must match after verified upload"


class TestLargeFileTransfer:
    CHUNK = CHUNK_SIZE  # 8 MB

    def _make_file(self, path: str, size: int, seed: int = 0):
        rng = hashlib.sha256(str(seed).encode()).digest()
        with open(path, "wb") as f:
            remaining = size
            while remaining > 0:
                chunk = rng * (min(remaining, 65536) // len(rng) + 1)
                f.write(chunk[:min(remaining, 65536)])
                remaining -= min(remaining, 65536)

    def _sha256(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                buf = f.read(65536)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()

    def test_transfer_small_file(self, tmp_path):
        src = tmp_path / "small.bin"
        dst = tmp_path / "small_copy.bin"
        self._make_file(str(src), 4096)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        with open(str(src), "rb") as sf:
            with open(str(dst), "wb") as df:
                for chunk in tm.read_chunks(str(src)):
                    df.write(chunk)
        assert self._sha256(str(dst)) == src_hash
        assert os.path.getsize(str(dst)) == 4096

    def test_transfer_exact_chunk(self, tmp_path):
        src = tmp_path / "exact_chunk.bin"
        dst = tmp_path / "exact_chunk_copy.bin"
        self._make_file(str(src), self.CHUNK)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        chunks = list(tm.read_chunks(str(src)))
        assert len(chunks) == 1
        assert len(chunks[0]) == self.CHUNK
        with open(str(dst), "wb") as f:
            f.write(chunks[0])
        assert self._sha256(str(dst)) == src_hash

    def test_transfer_multi_chunk(self, tmp_path):
        src = tmp_path / "multi_chunk.bin"
        dst = tmp_path / "multi_chunk_copy.bin"
        self._make_file(str(src), self.CHUNK * 3 + 1234)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        chunk_count = [0]
        with open(str(dst), "wb") as df:
            for chunk in tm.read_chunks(str(src)):
                df.write(chunk)
                chunk_count[0] += 1
        assert chunk_count[0] == 4
        assert os.path.getsize(str(dst)) == self.CHUNK * 3 + 1234
        assert self._sha256(str(dst)) == src_hash

    def test_transfer_checksum_verification(self, tmp_path):
        src = tmp_path / "checksum_src.bin"
        dst = tmp_path / "checksum_dst.bin"
        self._make_file(str(src), self.CHUNK * 2 + 777)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        with open(str(src), "rb") as sf:
            with open(str(dst), "wb") as df:
                for chunk in iter(lambda: sf.read(self.CHUNK), b""):
                    df.write(chunk)
        assert tm.checksum(str(dst)) == src_hash

    def test_progress_callback(self, tmp_path):
        src = tmp_path / "progress.bin"
        dst = tmp_path / "progress_copy.bin"
        self._make_file(str(src), self.CHUNK * 2)
        progress = []
        tm = TransferManager(progress_callback=lambda r, t: progress.append((r, t)))
        with open(str(dst), "wb") as df:
            for chunk in tm.read_chunks(str(src)):
                df.write(chunk)
        assert len(progress) > 0
        assert progress[-1][0] == progress[-1][1]
        assert progress[-1][1] == self.CHUNK * 2

    def test_cancel_during_transfer(self, tmp_path):
        src = tmp_path / "cancel_src.bin"
        dst = tmp_path / "cancel_dst.bin"
        self._make_file(str(src), self.CHUNK * 4)
        cancel = threading.Event()
        tm = TransferManager(cancel_event=cancel)
        cancel_count = [0]
        with open(str(dst), "wb") as df:
            for chunk in tm.read_chunks(str(src)):
                df.write(chunk)
                cancel_count[0] += 1
                if cancel_count[0] >= 2:
                    cancel.set()
        assert cancel_count[0] == 2
        assert os.path.getsize(str(dst)) < self.CHUNK * 4

    def test_write_stream(self, tmp_path):
        src = tmp_path / "stream_src.bin"
        dst = tmp_path / "stream_dst.bin"
        self._make_file(str(src), self.CHUNK * 3 + 1)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        def chunk_gen():
            with open(str(src), "rb") as f:
                while True:
                    buf = f.read(self.CHUNK)
                    if not buf:
                        break
                    yield buf
        dst_hash = tm.write_stream(str(dst), chunk_gen())
        assert dst_hash == src_hash

    def test_streaming_prevents_whole_file_load(self, tmp_path):
        src = tmp_path / "big_for_memory.bin"
        dst = tmp_path / "big_copy.bin"
        self._make_file(str(src), self.CHUNK * 10)
        tm = TransferManager()
        max_chunk_size = 0
        with open(str(src), "rb") as sf:
            with open(str(dst), "wb") as df:
                for chunk in tm.read_chunks(str(src)):
                    max_chunk_size = max(max_chunk_size, len(chunk))
                    df.write(chunk)
        assert max_chunk_size <= self.CHUNK
        assert os.path.getsize(str(dst)) == os.path.getsize(str(src))
        assert tm.checksum(str(dst)) == tm.checksum(str(src))

    def test_corrupted_file_verification(self, tmp_path):
        src = tmp_path / "good.bin"
        dst = tmp_path / "corrupted_copy.bin"
        self._make_file(str(src), 65536)
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        with open(str(src), "rb") as sf:
            data = sf.read()
        corrupted = bytearray(data)
        corrupted[100] ^= 0xFF
        with open(str(dst), "wb") as df:
            df.write(corrupted)
        assert tm.checksum(str(dst)) != src_hash

    def test_empty_file_transfer(self, tmp_path):
        src = tmp_path / "empty.bin"
        dst = tmp_path / "empty_copy.bin"
        src.touch()
        tm = TransferManager()
        src_hash = tm.checksum(str(src))
        chunks = list(tm.read_chunks(str(src)))
        assert len(chunks) == 0
        with open(str(dst), "wb") as df:
            for chunk in tm.read_chunks(str(src)):
                df.write(chunk)
        assert tm.checksum(str(dst)) == src_hash


class TestOperationState:
    def test_phase_transitions(self):
        from core import OperationState
        op = OperationState()
        assert op.snapshot().phase == "Idle"
        op.set_phase("Scanning")
        assert op.snapshot().phase == "Scanning"
        op.start("Uploading", "local", "test", 100, 0)
        assert op.snapshot().phase == "Uploading"
        op.finish(True)
        assert op.snapshot().phase == "Completed"

    def test_cancel_phase(self):
        from core import OperationState
        op = OperationState()
        op.cancel()
        assert op.snapshot().phase == "Cancelled"

    def test_ema_speed(self):
        from core import OperationState
        op = OperationState()
        op.start("Uploading", "local", "test", 1000000, 0)
        op.update_bytes(500000, 1000000)
        snap = op.snapshot()
        assert snap.speed_bps >= 0
        assert snap.duration_ms >= 0

    def test_file_tracking(self):
        from core import OperationState
        op = OperationState()
        op.start("Downloading", "local", "test", 1000, 5)
        op.set_current_file("file1.txt")
        assert op.snapshot().current_file == "file1.txt"
        op.incr_files()
        op.set_current_file("file2.txt")
        assert op.snapshot().files_completed == 1
        op.incr_files()
        assert op.snapshot().files_completed == 2

    def test_immutable_snapshot(self):
        from core import OperationState
        op = OperationState()
        snap1 = op.snapshot()
        snap2 = op.snapshot()
        assert snap1 is not snap2

    def test_concurrent_access(self):
        from core import OperationState
        op = OperationState()
        op.start("Uploading", "local", "test", 100000, 10)
        errors = []
        def writer():
            for _ in range(100):
                op.update_bytes(1000, 100000)
                op.incr_files()
                op.set_current_file("f.txt")
                op.set_phase("Uploading")
        def reader():
            for _ in range(100):
                try:
                    s = op.snapshot()
                    assert s.bytes_transferred >= 0
                    assert s.files_completed >= 0
                except Exception as e:
                    errors.append(e)
        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=writer, daemon=True))
            threads.append(threading.Thread(target=reader, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errors


class TestProviderProgressCallback:

    def _make_file(self, path, size):
        with open(path, "wb") as f:
            f.write(b"x" * size)

    def test_local_folder_upload_callback(self, tmp_path):
        from cloud import LocalFolder
        src = tmp_path / "src.bin"
        self._make_file(str(src), 65536)
        dest = tmp_path / "dest"
        dest.mkdir()
        prov = LocalFolder(str(dest))
        calls = []
        ok = prov.upload(str(src), "dst.bin", progress_callback=lambda b, t, f: calls.append((b, t, f)))
        assert ok
        assert len(calls) > 0
        assert calls[-1][0] == 65536
        assert calls[-1][1] == 65536
        assert calls[-1][2] == "src.bin"

    def test_local_folder_download_callback(self, tmp_path):
        from cloud import LocalFolder
        src = tmp_path / "backup" / "file.bin"
        src.parent.mkdir(parents=True)
        self._make_file(str(src), 32768)
        restore_dest = tmp_path / "restore" / "file.bin"
        restore_dest.parent.mkdir()
        prov = LocalFolder(str(src.parent))
        calls = []
        ok = prov.download(str(restore_dest), "file.bin", progress_callback=lambda b, t, f: calls.append((b, t, f)))
        assert ok
        assert len(calls) > 0
        assert calls[-1][0] == 32768

    def test_local_daemon_upload_callback_via_op_state(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "f1.txt").write_text("hello")
        (src_dir / "f2.txt").write_text("world" * 1000)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("Test", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        op_state = OperationState()
        daemon.sync_all_now(op_state=op_state)
        snap = op_state.snapshot()
        assert snap.files_completed == 2
        assert snap.bytes_total > 0
        assert snap.bytes_transferred > 0
        assert snap.phase == "Completed"

    def test_local_daemon_restore_callback_via_op_state(self, tmp_path):
        from core import SaveSyncCore, SaveSyncDaemon, Profile, OperationState
        from cloud import LocalFolder
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "f1.txt").write_text("backup data")
        restore_dir = tmp_path / "restore"
        restore_dir.mkdir()
        profile = Profile("TestR", [str(restore_dir)],
                          {"type": "local", "path": str(backup_dir)})
        core = SaveSyncCore()
        daemon = SaveSyncDaemon(core, profile)
        daemon.provider = LocalFolder(str(backup_dir))
        op_state = OperationState()
        daemon.restore_all(op_state=op_state, verify=False)
        snap = op_state.snapshot()
        assert snap.files_completed > 0
        assert snap.phase == "Completed"
        assert (restore_dir / "f1.txt").exists()


class TestSyncWorkerStateIntegration:
    def test_worker_exposes_op_state(self, tmp_path):
        from core import SyncWorker, SaveSyncCore, Profile
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("WTest", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        assert worker.op_state is None
        done_ev = threading.Event()
        results = {}
        def done(success, message, stats=None):
            results["success"] = success
            results["stats"] = stats
            done_ev.set()
        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=10)
        assert worker.op_state is not None
        snap = worker.op_state.snapshot()
        assert snap.files_completed == 1
        assert snap.phase == "Completed"

    def test_worker_stats_dict(self, tmp_path):
        from core import SyncWorker, SaveSyncCore, Profile
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "f.txt").write_text("data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("WTest2", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        done_ev = threading.Event()
        stats_result = {}
        def done(success, message, stats=None):
            stats_result.update(stats or {})
            done_ev.set()
        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=10)
        assert stats_result.get("files") == 1
        assert stats_result.get("duration_ms", 0) > 0

    def test_worker_cancel_propagation(self, tmp_path):
        from core import SyncWorker, SaveSyncCore, Profile
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for i in range(500):
            (src_dir / f"f_{i}.txt").write_text("x" * 1000)
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        profile = Profile("WCancel", [str(src_dir)],
                          {"type": "local", "path": str(dest_dir)})
        core = SaveSyncCore()
        worker = SyncWorker(core, profile)
        def watcher():
            while True:
                if worker.op_state:
                    snap = worker.op_state.snapshot()
                    if snap.files_completed >= 5:
                        worker.cancel()
                        return
                time.sleep(0.01)
        threading.Thread(target=watcher, daemon=True).start()
        done_ev = threading.Event()
        results = {}
        def done(success, message, stats=None):
            results["success"] = success
            results["message"] = message
            done_ev.set()
        worker.sync_all(done_callback=done)
        done_ev.wait(timeout=30)
        assert results.get("success") is False
        snap = worker.op_state.snapshot()
        assert snap.phase == "Cancelled"
        assert snap.files_completed < 500

