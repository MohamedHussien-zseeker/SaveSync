"""Credential store abstraction — Windows DPAPI (ctypes), system keyring, no persistence fallback."""
import base64
import ctypes
import ctypes.wintypes
import json
import os
import platform
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


SYSTEM = platform.system()


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_P_CRYPTPROTECT_PROMPTSTRUCT = ctypes.c_void_p

try:
    _crypt32 = ctypes.windll.crypt32
    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        _P_CRYPTPROTECT_PROMPTSTRUCT,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _CryptProtectData.restype = ctypes.wintypes.BOOL

    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        _P_CRYPTPROTECT_PROMPTSTRUCT,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _CryptUnprotectData.restype = ctypes.wintypes.BOOL
    _HAS_DPAPI = True
except Exception:
    _HAS_DPAPI = False


def _dpapi_encrypt(plain: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI using ctypes. Returns encrypted blob."""
    data_in = _DATA_BLOB(len(plain), ctypes.cast(plain, ctypes.POINTER(ctypes.c_byte)))
    data_out = _DATA_BLOB()
    if not _CryptProtectData(
        ctypes.byref(data_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(data_out),
    ):
        raise ctypes.WinError()
    raw = ctypes.cast(data_out.pbData, ctypes.POINTER(ctypes.c_byte * data_out.cbData))
    result = bytes(raw.contents)
    _crypt32.LocalFree(data_out.pbData)
    return result


def _dpapi_decrypt(blob: bytes) -> bytes:
    """Decrypt DPAPI-encrypted blob using ctypes. Returns plain bytes."""
    data_in = _DATA_BLOB(len(blob), ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)))
    data_out = _DATA_BLOB()
    desc_ptr = ctypes.wintypes.LPWSTR()
    if not _CryptUnprotectData(
        ctypes.byref(data_in),
        ctypes.byref(desc_ptr),
        None,
        None,
        None,
        0,
        ctypes.byref(data_out),
    ):
        raise ctypes.WinError()
    raw = ctypes.cast(data_out.pbData, ctypes.POINTER(ctypes.c_byte * data_out.cbData))
    result = bytes(raw.contents)
    _crypt32.LocalFree(data_out.pbData)
    if desc_ptr:
        _crypt32.LocalFree(desc_ptr)
    return result


_credential_warning_issued = False


def _warn_once(msg: str):
    global _credential_warning_issued
    if not _credential_warning_issued:
        print(f"[SaveSync] WARNING: {msg}", file=sys.stderr)
        _credential_warning_issued = True


class CredentialStore(ABC):
    @abstractmethod
    def store(self, service: str, account: str, secret: str) -> None:
        ...

    @abstractmethod
    def get(self, service: str, account: str) -> Optional[str]:
        ...

    @abstractmethod
    def delete(self, service: str, account: str) -> bool:
        ...

    @abstractmethod
    def list_accounts(self, service: str) -> List[str]:
        ...

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def available(self) -> bool:
        ...


class WindowsDPAPICredentialStore(CredentialStore):
    """Encrypts secrets with Windows DPAPI (CryptProtectData via ctypes crypt32.dll)."""

    def __init__(self):
        self._ok = _HAS_DPAPI

    def _encrypt(self, plain: str) -> str:
        data = plain.encode("utf-16-le")
        encrypted = _dpapi_encrypt(data)
        return base64.b64encode(encrypted).decode("ascii")

    def _decrypt(self, blob_b64: str) -> str:
        blob = base64.b64decode(blob_b64)
        data = _dpapi_decrypt(blob)
        return data.decode("utf-16-le")

    def _path(self, service: str, account: str) -> Path:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        safe = f"{service}_{account}".replace("/", "_").replace("\\", "_")
        store_dir = base / "SaveSync" / "credentials"
        store_dir.mkdir(parents=True, exist_ok=True)
        return store_dir / f"{safe}.enc"

    def store(self, service: str, account: str, secret: str) -> None:
        if not self._ok:
            raise RuntimeError("Windows DPAPI not available")
        blob = self._encrypt(secret)
        self._path(service, account).write_text(
            json.dumps({"v": 2, "d": blob, "a": account}), encoding="utf-8")

    def get(self, service: str, account: str) -> Optional[str]:
        if not self._ok:
            return None
        path = self._path(service, account)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._decrypt(data["d"])
        except Exception:
            return None

    def delete(self, service: str, account: str) -> bool:
        path = self._path(service, account)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_accounts(self, service: str) -> List[str]:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        store_dir = base / "SaveSync" / "credentials"
        if not store_dir.exists():
            return []
        prefix = f"{service}_"
        accounts = []
        for f in store_dir.iterdir():
            if f.suffix == ".enc" and f.stem.startswith(prefix):
                accounts.append(f.stem[len(prefix):])
        return accounts

    def name(self) -> str:
        return f"WindowsDPAPICredentialStore(available={self._ok})"

    def available(self) -> bool:
        return self._ok


class KeyringCredentialStore(CredentialStore):
    """Delegates to the system keyring (Gnome Keyring, KDE Wallet, macOS Keychain)."""

    def __init__(self):
        self._ok = None

    def _check(self):
        if self._ok is not None:
            return self._ok
        try:
            import keyring
            keyring.get_keyring()
            self._ok = True
        except Exception:
            self._ok = False
        return self._ok

    def store(self, service: str, account: str, secret: str) -> None:
        if not self._check():
            raise RuntimeError("System keyring not available")
        import keyring
        keyring.set_password(service, account, secret)

    def get(self, service: str, account: str) -> Optional[str]:
        if not self._check():
            return None
        import keyring
        return keyring.get_password(service, account)

    def delete(self, service: str, account: str) -> bool:
        if not self._check():
            return False
        import keyring
        try:
            keyring.delete_password(service, account)
            return True
        except Exception:
            return False

    def list_accounts(self, service: str) -> List[str]:
        return []

    def name(self) -> str:
        return f"KeyringCredentialStore(available={self._ok})"

    def available(self) -> bool:
        return self._check()


class EphemeralCredentialStore(CredentialStore):
    """In-memory only. Does not persist across restarts."""

    def __init__(self):
        self._store: Dict[str, Dict[str, str]] = {}

    def store(self, service: str, account: str, secret: str) -> None:
        if service not in self._store:
            self._store[service] = {}
        self._store[service][account] = secret

    def get(self, service: str, account: str) -> Optional[str]:
        return self._store.get(service, {}).get(account)

    def delete(self, service: str, account: str) -> bool:
        if service in self._store and account in self._store[service]:
            del self._store[service][account]
            return True
        return False

    def list_accounts(self, service: str) -> List[str]:
        return list(self._store.get(service, {}).keys())

    def name(self) -> str:
        return "EphemeralCredentialStore(in-memory, not persisted)"

    def available(self) -> bool:
        return True


def get_credential_store() -> CredentialStore:
    if SYSTEM == "Windows":
        dpapi = WindowsDPAPICredentialStore()
        if dpapi.available():
            return dpapi
        kr = KeyringCredentialStore()
        if kr.available():
            return kr
        _warn_once(
            "No secure credential storage available (crypt32.dll/keyring not found). "
            "Provider tokens will NOT be saved between sessions. "
            "Install 'keyring' for persistent encrypted storage on Windows.")
        return EphemeralCredentialStore()
    kr = KeyringCredentialStore()
    if kr.available():
        return kr
    _warn_once(
        "No system keyring available (install 'keyring' for persistent storage). "
        "Provider tokens will NOT be saved between sessions. "
        "Install the 'keyring' package for your platform.")
    return EphemeralCredentialStore()


def redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if any(secret_word in k.lower() for secret_word in ("token", "secret", "password", "credential", "key", "auth")):
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    return obj
