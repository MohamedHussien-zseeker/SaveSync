import copy
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from cloud import CloudProvider, create_provider
from logging_system import get_logging_system, log_error, shutdown as log_shutdown
from state import OperationState
from credential_store import get_credential_store, CredentialStore, redact_secrets
from providers import (
    Account, ProviderRegistry, ProviderAdapter,
    get_provider_registry, LocalAdapter,
)


def _log_path() -> Path:
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).parent.resolve()
    else:
        app_dir = Path(sys.argv[0]).parent.resolve()
    try:
        test = app_dir / ".writable_test"
        test.touch()
        test.unlink()
        return app_dir / "savesync.log"
    except (OSError, PermissionError):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        log_dir = base / "SaveSync"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "savesync.log"


def setup_file_logger(gui_handler=None) -> logging.Logger:
    logger = logging.getLogger("savesync")
    logger.setLevel(logging.DEBUG)
    log_file = _log_path()
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.handlers.clear()
    logger.addHandler(fh)
    if gui_handler:
        logger.addHandler(gui_handler)
    return logger


def _detect_watcher():
    try:
        import pyinotify
        return "inotify"
    except ImportError:
        return "poll"


ACCOUNTS_FILE = Path(os.path.expanduser("~/.config/savesync/accounts.json"))


class Profile:
    def __init__(self, name: str, watch_dirs: List[str],
                 provider_config: Optional[dict] = None,
                 sync_on_close: bool = False,
                 account_ref: Optional[str] = None):
        self.name = name
        self.watch_dirs = watch_dirs
        self.provider_config = provider_config or {"type": "local", "path": os.path.expanduser("~/SaveSyncBackup")}
        self.sync_on_close = sync_on_close
        self.account_ref = account_ref

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "watch_dirs": self.watch_dirs,
            "provider_config": self.provider_config,
            "sync_on_close": self.sync_on_close,
            "account_ref": self.account_ref,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            name=d["name"],
            watch_dirs=d.get("watch_dirs", []),
            provider_config=d.get("provider_config"),
            sync_on_close=d.get("sync_on_close", False),
            account_ref=d.get("account_ref"),
        )


@dataclass(frozen=True)
class OperationContext:
    """Immutable snapshot of profile data for use in worker threads."""
    op_id: str
    profile_name: str
    watch_dirs: Tuple[str, ...]
    provider_config: Mapping[str, Any]
    provider_type: str
    sync_on_close: bool


class GuiLogHandler(logging.Handler):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            tag = "INFO"
            if record.levelname in ("ERROR", "CRITICAL"):
                tag = "ERROR"
            elif record.levelname == "WARNING":
                tag = "WARN"
            elif "sync" in record.getMessage().lower():
                tag = "SYNC"
            self.widget.insert("end", msg + "\n", tag)
            self.widget.see("end")
        except Exception:
            pass  # Tkinter widget may be destroyed at shutdown


class SaveSyncCore:
    CONFIG_DIR = Path(os.path.expanduser("~/.config/savesync"))
    PROFILES_FILE = CONFIG_DIR / "profiles.json"

    def __init__(self):
        self.log_handler = print
        self.logger: logging.Logger = None
        self.profiles: "List[Profile]" = []
        self.accounts: "List[Account]" = []
        self._profiles_lock = threading.Lock()
        self.credential_store: CredentialStore = get_credential_store()
        self.provider_registry: ProviderRegistry = get_provider_registry()
        self.logging = get_logging_system()
        self._load_profiles()
        self._load_accounts()
        self._migrate_legacy_tokens()

    def _ensure_config(self):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_profiles(self):
        self._ensure_config()
        with self._profiles_lock:
            if self.PROFILES_FILE.exists():
                try:
                    data = json.loads(self.PROFILES_FILE.read_text())
                    self.profiles = [Profile.from_dict(p) for p in data]
                except (json.JSONDecodeError, KeyError) as e:
                    self.logging.errors.capture("core", e)
                    self.profiles = []
            if not self.profiles:
                self.profiles.append(Profile("Default", [], {"type": "local"}))

    def _load_accounts(self):
        with self._profiles_lock:
            if ACCOUNTS_FILE.exists():
                try:
                    data = json.loads(ACCOUNTS_FILE.read_text())
                    self.accounts = [Account.from_dict(a) for a in data]
                except (json.JSONDecodeError, Exception) as e:
                    self.logging.errors.capture("core", e)
                    self.accounts = []

    def save_profiles(self):
        self._ensure_config()
        with self._profiles_lock:
            data = [p.to_dict() for p in self.profiles]
            self.PROFILES_FILE.write_text(json.dumps(data, indent=2))
            names = [p.name for p in self.profiles]
        self.logging.audit.setting_changed("profiles", None, names)

    def save_accounts(self):
        self._ensure_config()
        with self._profiles_lock:
            data = [a.to_dict() for a in self.accounts]
            ACCOUNTS_FILE.write_text(json.dumps(data, indent=2))

    def log(self, msg: str):
        if self.logger:
            self.logger.info(msg)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_handler(f"[{ts}] {msg}")

    def get_provider(self, profile: Profile) -> CloudProvider:
        prov = create_provider(profile.provider_config)
        prov.log_handler = self.log_handler
        prov.logger = self.logger
        prov.logging = self.logging
        return prov

    def get_adapter_for_profile(self, profile: Profile) -> Optional[ProviderAdapter]:
        account = None
        if profile.account_ref:
            account = self.get_account(profile.account_ref)
        if account:
            return self.provider_registry.get_instance_for_account(account)
        prov_type = profile.provider_config.get("type", "local")
        adapter = self.provider_registry.get_instance(prov_type)
        if adapter and prov_type == "local":
            adapter.dest_root = profile.provider_config.get(
                "path", os.path.expanduser("~/SaveSyncBackup"))
        return adapter

    def get_account(self, account_id: str) -> Optional[Account]:
        with self._profiles_lock:
            for a in self.accounts:
                if a.account_id == account_id:
                    return a
        return None

    def add_account(self, account: Account):
        with self._profiles_lock:
            existing = None
            for a in self.accounts:
                if a.account_id == account.account_id:
                    existing = a
                    break
            if existing:
                self.accounts.remove(existing)
            self.accounts.append(account)
        self.save_accounts()

    def remove_account(self, account_id: str) -> bool:
        with self._profiles_lock:
            account = None
            for a in self.accounts:
                if a.account_id == account_id:
                    account = a
                    break
        if account:
            adapter = self.provider_registry.get_instance_for_account(account)
            if adapter:
                adapter.disconnect(account)
            with self._profiles_lock:
                self.accounts = [a for a in self.accounts if a.account_id != account_id]
            self.save_accounts()
            return True
        return False

    def _migrate_legacy_tokens(self):
        migrated = 0
        with self._profiles_lock:
            profiles = list(self.profiles)
        for profile in profiles:
            config = profile.provider_config
            prov_type = config.get("type", "local")
            if prov_type == "dropbox" and "token" in config:
                token = config["token"]
                if token and not profile.account_ref:
                    account_id = f"migrated_dropbox_{uuid.uuid4().hex[:8]}"
                    account = Account(
                        provider="dropbox",
                        account_id=account_id,
                        display_name="Dropbox (migrated)",
                        display_email="",
                        credential_ref="",
                        connected_at=datetime.now().isoformat(),
                        provider_config={"remote_root": config.get("remote_root", "/SaveSync")},
                    )
                    self.credential_store.store(
                        "savesync", account_id, json.dumps({"access_token": token}))
                    account.credential_ref = account_id
                    self.accounts.append(account)
                    profile.account_ref = account_id
                    profile.provider_config["type"] = "dropbox"
                    del profile.provider_config["token"]
                    migrated += 1

            elif prov_type == "google_drive" and "credentials" in config:
                creds = config["credentials"]
                if creds and not profile.account_ref:
                    account_id = f"migrated_gdrive_{uuid.uuid4().hex[:8]}"
                    account = Account(
                        provider="google_drive",
                        account_id=account_id,
                        display_name="Google Drive (migrated)",
                        display_email="",
                        credential_ref="",
                        connected_at=datetime.now().isoformat(),
                        provider_config={"folder_type": "appDataFolder"},
                    )
                    client_id = creds.get("client_id", "")
                    client_secret = creds.get("client_secret", "")
                    account.provider_config["client_id"] = client_id
                    account.provider_config["client_secret"] = client_secret
                    self.credential_store.store(
                        "savesync", account_id, json.dumps({"raw_credentials": creds}))
                    account.credential_ref = account_id
                    self.accounts.append(account)
                    profile.account_ref = account_id
                    profile.provider_config["type"] = "google_drive"
                    del profile.provider_config["credentials"]
                    migrated += 1

        if migrated > 0:
            self.save_profiles()
            self.save_accounts()
            self.log(f"Migrated {migrated} legacy token(s) to credential store")


class SaveSyncDaemon:
    POLL_INTERVAL = 2.0

    def __init__(self, core: SaveSyncCore, profile: Profile):
        self.core = core
        self.profile = profile
        self.provider = core.get_provider(profile)
        config_copy = copy.deepcopy(dict(profile.provider_config or {}))
        self.ctx = OperationContext(
            op_id="op_" + uuid.uuid4().hex[:8],
            profile_name=profile.name,
            watch_dirs=tuple(profile.watch_dirs),
            provider_config=MappingProxyType(config_copy),
            provider_type=config_copy.get("type", "local"),
            sync_on_close=profile.sync_on_close,
        )
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._watcher_type = _detect_watcher()
        self._inotify_instance = None
        self._snapshots: "Dict[str, Dict[str, float]]" = {}
        self._pending: "set[str]" = set()
        self._pending_lock = threading.Lock()
        self._snapshots_lock = threading.Lock()
        self._debounce_timer: "Optional[threading.Timer]" = None
        self._sync_id = "sync_" + uuid.uuid4().hex[:8]
        self._log = core.logging

    def _scan(self, directory: str) -> "Dict[str, float]":
        result = {}
        for root, _dirs, files in os.walk(directory):
            for f in files:
                path = os.path.join(root, f)
                try:
                    result[path] = os.path.getmtime(path)
                except OSError:
                    pass  # skip unreadable files
        return result

    def _rel_path(self, full_path: str) -> str:
        for wd in self.ctx.watch_dirs:
            try:
                rel = os.path.relpath(full_path, wd)
                if not rel.startswith("..") and rel != ".":
                    return rel
            except ValueError:
                pass  # path not under watch dir, use basename
        return os.path.basename(full_path)

    def _sync_path(self, path: str):
        if not os.path.isfile(path):
            return
        rel = self._rel_path(path)
        size = os.path.getsize(path)
        ok = self.provider.upload(path, rel)
        if ok:
            self.core.log(f"Synced: {rel}")
            self._log.sync.file_uploaded(rel, size)
            self._log.fs.modified(path, size)

    def _debounce_sync(self, path: str):
        with self._pending_lock:
            self._pending.add(path)
        if self._debounce_timer and self._debounce_timer.is_alive():
            self._debounce_timer.cancel()
        self._debounce_timer = threading.Timer(1.0, self._flush_pending)
        self._debounce_timer.start()

    def _flush_pending(self):
        with self._pending_lock:
            paths = list(self._pending)
            self._pending.clear()
        for p in paths:
            self._sync_path(p)

    def _inotify_loop(self):
        import pyinotify
        mask = pyinotify.IN_CLOSE_WRITE | pyinotify.IN_MOVED_TO | pyinotify.IN_CREATE

        class Handler(pyinotify.ProcessEvent):
            def __init__(self, daemon):
                self.daemon = daemon

            def process_IN_CLOSE_WRITE(self, event):
                self.daemon._debounce_sync(event.pathname)
                self.daemon._log.fs.modified(event.pathname)

            def process_IN_MOVED_TO(self, event):
                self.daemon._debounce_sync(event.pathname)
                self.daemon._log.fs.created(event.pathname)

            def process_IN_CREATE(self, event):
                if not event.dir:
                    self.daemon._debounce_sync(event.pathname)
                    self.daemon._log.fs.created(event.pathname)

        wm = pyinotify.WatchManager()
        handler = Handler(self)
        self._inotify_instance = pyinotify.Notifier(wm, handler)
        for d in self.ctx.watch_dirs:
            if os.path.isdir(d):
                wm.add_watch(d, mask, rec=True, auto_add=True)
                self.core.log(f"Inotify watching: {d}")
        self._inotify_instance.loop()

    def _poll_loop(self):
        for d in self.ctx.watch_dirs:
            if os.path.isdir(d):
                with self._snapshots_lock:
                    self._snapshots[d] = self._scan(d)
                self.core.log(f"Poll watching: {d} ({len(self._snapshots[d])} files)")
        while self.running:
            for d in self.ctx.watch_dirs:
                if not os.path.isdir(d):
                    continue
                current = self._scan(d)
                with self._snapshots_lock:
                    prev = self._snapshots.get(d, {})
                new_files = {p for p in current if p not in prev}
                mod_files = {p for p in current if p in prev and current[p] != prev[p]}
                for path in new_files | mod_files:
                    self._sync_path(path)
                with self._snapshots_lock:
                    self._snapshots[d] = current
            time.sleep(self.POLL_INTERVAL)

    def start(self):
        self.running = True
        if self._watcher_type == "inotify":
            self._thread = threading.Thread(target=self._inotify_loop, daemon=True)
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        folders = ", ".join(self.ctx.watch_dirs)
        prov = self.provider.name if self.provider else ""
        self.core.log(f"Sync started ({self._watcher_type}, provider={prov})")
        self._log.sync.started(self._sync_id, folders, provider=prov)

    def stop(self):
        self.running = False
        if self._inotify_instance:
            self._inotify_instance.stop()
        self._flush_pending()
        self.core.log("Sync stopped")
        self._log.sync.completed(self._sync_id)

    def sync_all_now(self, op_state=None, cancel_event=None):
        prov = self.provider.name if self.provider else ""
        op_id = self.ctx.op_id
        sync_id = "sync_" + uuid.uuid4().hex[:8]
        folders = ", ".join(self.ctx.watch_dirs)
        self._log.sync.started(sync_id, folders, provider=prov)
        self._log.audit.action("sync_started", {"op_id": op_id, "profile": self.ctx.profile_name})

        if op_state:
            op_state.set_phase("Scanning")

        all_files = []
        total_bytes = 0
        for d in self.ctx.watch_dirs:
            if os.path.isdir(d):
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        fpath = os.path.join(root, f)
                        all_files.append(fpath)
                        try:
                            total_bytes += os.path.getsize(fpath)
                        except OSError:
                            pass

        if op_state:
            op_state.start("Uploading", prov, self.ctx.profile_name,
                           len(all_files), total_bytes)

        t0 = time.time()
        count = 0
        errors = 0
        bytes_before = 0
        for path in all_files:
            if cancel_event and cancel_event.is_set():
                dur = (time.time() - t0) * 1000
                self.core.log("Sync cancelled")
                self._log.sync.failed(sync_id, "Cancelled",
                                      error_code="SS7000",
                                      provider=prov, duration_ms=dur)
                if op_state:
                    op_state.cancel()
                return
            rel = self._rel_path(path)
            fsize = os.path.getsize(path)
            fname = os.path.basename(path)

            def _file_progress(fn, bb, fs):
                def cb(b, t, *a):
                    if op_state:
                        op_state.update_bytes(bb + b, total_bytes)
                return cb

            if op_state:
                op_state.set_current_file(fname)
            ok = self.provider.upload(
                path, rel,
                progress_callback=_file_progress(fname, bytes_before, fsize),
            )
            if ok:
                bytes_before += fsize
                if op_state:
                    op_state.update_bytes(bytes_before, total_bytes)
                    op_state.incr_files()
                self.core.log(f"Synced: {rel}")
                self._log.sync.file_uploaded(rel, fsize)
                self._log.fs.modified(path, fsize)
            else:
                errors += 1
                self.core.log(f"FAILED: {rel}")
            count += 1

        dur = (time.time() - t0) * 1000
        self.core.log(f"Full sync complete: {count} files ({errors} errors)")
        if errors:
            self._log.sync.failed(sync_id, f"{errors} file(s) failed",
                                  error_code="SS3001",
                                  provider=prov, duration_ms=dur)
        else:
            self._log.sync.completed(sync_id, count, duration_ms=dur, provider=prov)
        if op_state:
            op_state.finish(errors == 0)

    def _pre_restore_backup(self, dest: str) -> str:
        if not os.path.exists(dest):
            return ""
        backup_dir = os.path.join(os.path.dirname(dest), ".savesync_restore_backup")
        os.makedirs(backup_dir, exist_ok=True)
        rel = os.path.basename(dest)
        backup_path = os.path.join(backup_dir, f"{rel}.bak")
        try:
            import shutil
            shutil.copy2(dest, backup_path)
            return backup_path
        except Exception as e:
            self.core.log(f"Pre-restore backup failed for {dest}: {e}")
            return ""

    def _verify_checksum(self, path: str) -> str:
        import hashlib
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            self.core.log(f"Checksum verification failed for {path}: {e}")
            return ""

    def restore_all(self, op_state=None, cancel_event=None, verify=True):
        op_id = self.ctx.op_id
        self.core.log("Starting restore...")
        self._log.audit.action("restore_started",
                               {"op_id": op_id, "profile": self.ctx.profile_name})
        prov = self.provider.name if self.provider else ""

        if op_state:
            op_state.set_phase("Scanning")

        remote_files = self.provider.list_files()
        if not remote_files:
            self.core.log("No backup files found to restore")
            self._log.sync.failed(self._sync_id, "No backup files found",
                                  error_code="SS3001", provider=prov)
            if op_state:
                op_state.finish(False)
            return

        total_files = len(remote_files)
        rmt = self.provider
        total_bytes = 0
        if hasattr(rmt, "dest_root"):
            for rel in remote_files:
                p = os.path.join(rmt.dest_root, rel)
                try:
                    total_bytes += os.path.getsize(p)
                except OSError:
                    pass
        if op_state:
            op_state.start("Downloading", prov, self.ctx.profile_name,
                           total_files, total_bytes)

        restored = 0; errors = 0; skipped = 0; verified = 0
        for i, rel in enumerate(remote_files):
            if cancel_event and cancel_event.is_set():
                self.core.log("Restore cancelled")
                if op_state:
                    op_state.cancel()
                return
            dest_path = None
            watch_dir_used = None
            for watch_dir in self.ctx.watch_dirs:
                candidate = os.path.join(watch_dir, rel)
                if not os.path.exists(candidate):
                    dest_path = candidate
                    watch_dir_used = watch_dir
                    break
            if dest_path is None:
                skipped += 1
                if op_state:
                    op_state.incr_files()
                continue
            dest_dir = os.path.dirname(dest_path)
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            success = False
            try:
                self._pre_restore_backup(dest_path)
                fname = os.path.basename(rel)

                def _dl_progress(bb, total_bytes_known):
                    def cb(b, t, *a):
                        if op_state:
                            op_state.update_bytes(bb + b, total_bytes_known)
                    return cb

                if op_state:
                    op_state.set_current_file(fname)
                ok = self.provider.download(
                    dest_path, rel,
                    progress_callback=_dl_progress(0, total_bytes or total_files),
                )
                if ok:
                    if verify:
                        sha = self._verify_checksum(dest_path)
                        if sha:
                            verified += 1
                            self.core.log(f"Verified SHA-256: {sha[:16]}... for {rel}")
                    self.core.log(f"Restored: {rel} to {watch_dir_used}")
                    self._log.sync.file_downloaded(rel)
                    restored += 1
                    success = True
                else:
                    errors += 1
            except Exception as e:
                self._log.errors.capture("restore", e,
                                         operation="restore", provider=prov)
                errors += 1
            if op_state:
                op_state.incr_files()
        self.core.log(
            f"Restore complete: {restored} restored, {skipped} skipped, "
            f"{errors} errors, {verified} verified")
        self._log.audit.action("restore_completed", {
            "restored": restored, "errors": errors, "skipped": skipped
        })
        if op_state:
            op_state.finish(True)


class SyncWorker:
    """Runs sync/restore in a background thread with progress and cancellation."""

    def __init__(self, core: SaveSyncCore, profile: Profile):
        self.core = core
        self.profile = profile
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._current_op: Optional[str] = None
        self.op_state: Optional[OperationState] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_op(self) -> Optional[str]:
        return self._current_op

    def sync_all(self, progress_callback=None, done_callback=None):
        if self.is_running:
            return False
        self.op_state = OperationState()
        self._current_op = "sync"
        self._cancel_event.clear()
        self._thread = threading.Thread(
            target=self._do_sync,
            args=(progress_callback, done_callback),
            daemon=True)
        self._thread.start()
        return True

    def restore_all(self, progress_callback=None, done_callback=None, verify=True):
        if self.is_running:
            return False
        self.op_state = OperationState()
        self._current_op = "restore"
        self._cancel_event.clear()
        self._thread = threading.Thread(
            target=self._do_restore,
            args=(progress_callback, done_callback, verify),
            daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel_event.set()
        if self.op_state:
            self.op_state.cancel()

    def _stats_dict(self):
        if not self.op_state:
            return {}
        ss = self.op_state.snapshot()
        return {
            "files": ss.files_completed,
            "bytes": ss.bytes_transferred,
            "duration_ms": ss.duration_ms,
            "speed_bps": ss.speed_bps,
        }

    def _do_sync(self, progress_callback, done_callback):
        try:
            daemon = SaveSyncDaemon(self.core, self.profile)
            daemon.sync_all_now(
                op_state=self.op_state,
                cancel_event=self._cancel_event)
            if not self._cancel_event.is_set():
                snap = self.op_state.snapshot() if self.op_state else None
                ok = snap is None or snap.phase == "Completed"
                if done_callback:
                    done_callback(ok, "Sync complete" if ok else "Sync failed", self._stats_dict())
            else:
                if done_callback:
                    done_callback(False, "Cancelled", self._stats_dict())
        except Exception as e:
            self.core.log(f"Sync failed: {e}")
            log_error("SyncWorker", e, operation="sync",
                      provider=self.profile.provider_config.get("type", ""))
            if done_callback:
                done_callback(False, str(e), self._stats_dict())
        finally:
            self._current_op = None

    def _do_restore(self, progress_callback, done_callback, verify):
        try:
            daemon = SaveSyncDaemon(self.core, self.profile)
            daemon.restore_all(
                op_state=self.op_state,
                cancel_event=self._cancel_event,
                verify=verify)
            if not self._cancel_event.is_set():
                if done_callback:
                    done_callback(True, "Restore complete", self._stats_dict())
            else:
                if done_callback:
                    done_callback(False, "Cancelled", self._stats_dict())
        except Exception as e:
            self.core.log(f"Restore failed: {e}")
            log_error("SyncWorker", e, operation="restore",
                      provider=self.profile.provider_config.get("type", ""))
            if done_callback:
                done_callback(False, str(e), self._stats_dict())
        finally:
            self._current_op = None
