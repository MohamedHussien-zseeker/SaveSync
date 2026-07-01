"""Configuration sync with conflict resolution — schema versioning, device IDs, backups."""
import json
import os
import platform
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from credential_store import get_credential_store, redact_secrets
from providers import Account, ProviderRegistry, ProviderAdapter, get_provider_registry


CONFIG_SCHEMA_VERSION = 1
CONFIG_FILENAME = "savesync_config.json"
CONFIG_BACKUP_PREFIX = "savesync_config_backup_"


def _get_device_id() -> str:
    device_file = Path.home() / ".config" / "savesync" / "device_id"
    if device_file.exists():
        return device_file.read_text().strip()
    device_file.parent.mkdir(parents=True, exist_ok=True)
    did = uuid.uuid4().hex[:12]
    device_file.write_text(did)
    return did


@dataclass
class DeviceConfig:
    device_id: str = field(default_factory=_get_device_id)
    device_name: str = field(default_factory=lambda: platform.node() or "unknown")
    platform: str = field(default_factory=platform.system)
    folder_mappings: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeviceConfig":
        return cls(
            device_id=d.get("device_id", _get_device_id()),
            device_name=d.get("device_name", platform.node()),
            platform=d.get("platform", platform.system()),
            folder_mappings=d.get("folder_mappings", {}),
        )


@dataclass
class SyncConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    config_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_by_device: str = field(default_factory=_get_device_id)
    profile_ids: List[str] = field(default_factory=list)
    profile_names: List[str] = field(default_factory=list)
    account_refs: List[Dict[str, str]] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    devices: Dict[str, DeviceConfig] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_id": self.config_id,
            "updated_at": self.updated_at,
            "updated_by_device": self.updated_by_device,
            "profile_ids": self.profile_ids,
            "profile_names": self.profile_names,
            "account_refs": self.account_refs,
            "preferences": redact_secrets(self.preferences),
            "devices": {k: v.to_dict() for k, v in self.devices.items()},
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SyncConfig":
        devices_raw = d.get("devices", {})
        devices = {}
        for k, v in devices_raw.items():
            if isinstance(v, dict):
                devices[k] = DeviceConfig.from_dict(v)
            else:
                devices[k] = v
        return cls(
            schema_version=d.get("schema_version", 1),
            config_id=d.get("config_id", uuid.uuid4().hex[:12]),
            updated_at=d.get("updated_at", ""),
            updated_by_device=d.get("updated_by_device", ""),
            profile_ids=d.get("profile_ids", []),
            profile_names=d.get("profile_names", []),
            account_refs=d.get("account_refs", []),
            preferences=d.get("preferences", {}),
            devices=devices,
        )


class ConfigSync:
    CONFIG_DIR = Path(os.path.expanduser("~/.config/savesync"))
    CACHE_FILE = CONFIG_DIR / "config_cache.json"

    def __init__(self, registry: Optional[ProviderRegistry] = None):
        self.registry = registry or get_provider_registry()
        self.log_handler: Callable[[str], None] = print
        self.logger: Any = None
        self._lock = threading.Lock()
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str):
        if self.logger:
            self.logger.info(msg)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_handler(f"[{ts}] {msg}")

    def _get_local_config(self) -> SyncConfig:
        if self.CACHE_FILE.exists():
            try:
                data = json.loads(self.CACHE_FILE.read_text())
                return SyncConfig.from_dict(data)
            except Exception:
                print("Failed to parse local config cache", file=sys.stderr)
        return SyncConfig()

    def _save_local_config(self, config: SyncConfig):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_FILE.write_text(
            json.dumps(config.to_dict(), indent=2), encoding="utf-8")

    def _read_remote_config(self, adapter: ProviderAdapter) -> Optional[SyncConfig]:
        temp_dir = self.CONFIG_DIR / ".sync_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / CONFIG_FILENAME
        try:
            ok = adapter.download(str(temp_file), CONFIG_FILENAME)
            if ok and temp_file.exists():
                data = json.loads(temp_file.read_text())
                temp_file.unlink(missing_ok=True)
                return SyncConfig.from_dict(data)
        except Exception:
            print("Failed to read remote config", file=sys.stderr)
        finally:
            temp_file.unlink(missing_ok=True)
        return None

    def _write_remote_config(self, adapter: ProviderAdapter,
                             config: SyncConfig) -> bool:
        temp_dir = self.CONFIG_DIR / ".sync_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / CONFIG_FILENAME
        try:
            temp_file.write_text(
                json.dumps(config.to_dict(), indent=2), encoding="utf-8")
            ok = adapter.upload(str(temp_file), CONFIG_FILENAME)
            return ok
        except Exception as e:
            self.log(f"Remote config write failed: {e}")
            return False
        finally:
            temp_file.unlink(missing_ok=True)

    def _create_backup(self, adapter: ProviderAdapter, config: SyncConfig):
        backup_name = f"{CONFIG_BACKUP_PREFIX}{config.config_id[:8]}_{config.updated_at[:10]}.json"
        temp_dir = self.CONFIG_DIR / ".sync_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / backup_name
        try:
            temp_file.write_text(
                json.dumps(config.to_dict(), indent=2), encoding="utf-8")
            adapter.upload(str(temp_file), backup_name)
        except Exception:
            print("Failed to create config backup", file=sys.stderr)
        finally:
            temp_file.unlink(missing_ok=True)

    def sync(self, account: Account, local_config: SyncConfig,
             conflict_callback: Optional[Callable[[SyncConfig, SyncConfig], str]] = None
             ) -> Tuple[bool, str, Optional[SyncConfig]]:
        adapter = self.registry.get_instance_for_account(account)
        if not adapter:
            return False, "no adapter", None

        remote = self._read_remote_config(adapter)

        if remote is None:
            self._write_remote_config(adapter, local_config)
            self._save_local_config(local_config)
            self.log("Config pushed to remote (first sync)")
            return True, "pushed", local_config

        local_time = _parse_iso(local_config.updated_at)
        remote_time = _parse_iso(remote.updated_at)

        if local_time >= remote_time:
            self._write_remote_config(adapter, local_config)
            self._save_local_config(local_config)
            self.log("Config pushed (local newer)")
            return True, "pushed", local_config

        if local_config.config_id == remote.config_id and abs(local_time - remote_time) < 5:
            self._save_local_config(remote)
            self.log("Config pulled (same config, synced)")
            return True, "pulled", remote

        has_conflict = False
        merged = SyncConfig(
            config_id=uuid.uuid4().hex[:12],
            updated_at=datetime.now(timezone.utc).isoformat(),
            updated_by_device=_get_device_id(),
        )
        merged.profile_ids = list(
            set(local_config.profile_ids) | set(remote.profile_ids))
        merged.profile_names = list(
            set(local_config.profile_names) | set(remote.profile_names))
        merged.preferences = {**remote.preferences, **local_config.preferences}
        merged.devices = {**remote.devices, **local_config.devices}

        local_account_refs = {r.get("account_id", ""): r
                              for r in local_config.account_refs}
        remote_account_refs = {r.get("account_id", ""): r
                               for r in remote.account_refs}
        merged.account_refs = list(
            {**remote_account_refs, **local_account_refs}.values())

        merged_profile_names = set(merged.profile_names)
        if len(merged.profile_names) != len(merged_profile_names):
            has_conflict = True
            merged.profile_names = list(merged_profile_names)

        if has_conflict and conflict_callback:
            decision = conflict_callback(local_config, remote_config)
            if decision == "local":
                self._create_backup(adapter, remote)
                self._write_remote_config(adapter, local_config)
                self._save_local_config(local_config)
                self.log("Conflict resolved: local wins")
                return True, "conflict_local", local_config
            elif decision == "remote":
                self._save_local_config(remote)
                self.log("Conflict resolved: remote wins")
                return True, "conflict_remote", remote
            elif decision == "merge":
                self._create_backup(adapter, remote)
                self._write_remote_config(adapter, merged)
                self._save_local_config(merged)
                self.log("Conflict resolved: merged")
                return True, "conflict_merged", merged

        self._create_backup(adapter, remote)
        self._write_remote_config(adapter, merged)
        self._save_local_config(merged)
        self.log("Config merged and synced")
        return True, "merged", merged

    def push(self, account: Account, local_config: SyncConfig) -> Tuple[bool, str]:
        adapter = self.registry.get_instance_for_account(account)
        if not adapter:
            return False, "no adapter"
        local_config.updated_at = datetime.now(timezone.utc).isoformat()
        local_config.updated_by_device = _get_device_id()
        ok = self._write_remote_config(adapter, local_config)
        if ok:
            self._save_local_config(local_config)
            self.log("Config pushed")
            return True, "pushed"
        return False, "write_failed"

    def pull(self, account: Account) -> Tuple[bool, str, Optional[SyncConfig]]:
        adapter = self.registry.get_instance_for_account(account)
        if not adapter:
            return False, "no adapter", None
        remote = self._read_remote_config(adapter)
        if remote:
            self._save_local_config(remote)
            self.log("Config pulled")
            return True, "pulled", remote
        return False, "not_found", None


def _parse_iso(iso_str: str) -> float:
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0
