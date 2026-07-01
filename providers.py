"""Provider registry and adapter pattern — Local, Dropbox, Google Drive, OneDrive."""
import json
import os
import platform
import secrets
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from credential_store import get_credential_store, CredentialStore, redact_secrets
from transfer import TransferManager, CHUNK_SIZE

SYSTEM = platform.system()


@dataclass
class Account:
    provider: str
    account_id: str
    display_email: str
    display_name: str
    capabilities: List[str] = field(default_factory=lambda: ["upload", "download", "list"])
    credential_ref: str = ""
    connected_at: str = ""
    provider_config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "account_id": self.account_id,
            "display_email": self.display_email,
            "display_name": self.display_name,
            "capabilities": self.capabilities,
            "credential_ref": self.credential_ref,
            "connected_at": self.connected_at,
            "provider_config": redact_secrets(self.provider_config),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Account":
        return cls(
            provider=d["provider"],
            account_id=d["account_id"],
            display_email=d.get("display_email", ""),
            display_name=d.get("display_name", ""),
            capabilities=d.get("capabilities", ["upload", "download", "list"]),
            credential_ref=d.get("credential_ref", ""),
            connected_at=d.get("connected_at", ""),
            provider_config=d.get("provider_config", {}),
        )


class OAuthResult:
    def __init__(self, access_token: str, refresh_token: str = "",
                 expires_at: float = 0, account_id: str = "",
                 display_email: str = "", display_name: str = "",
                 extra: Optional[Dict[str, Any]] = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.account_id = account_id
        self.display_email = display_email
        self.display_name = display_name
        self.extra = extra or {}


class ProviderAdapter(ABC):
    name: str = ""
    display_name: str = ""
    capabilities: List[str] = ["upload", "download", "list"]
    oauth_scopes: List[str] = []
    needs_client_config: bool = False
    client_config_label: str = ""
    client_config_hint: str = ""

    def __init__(self):
        self.log_handler: Callable[[str], None] = print
        self.logger: Any = None
        self.logging: Any = None
        self.credential_store: CredentialStore = get_credential_store()
        self._account: Optional[Account] = None

    def log(self, msg: str):
        if self.logger:
            self.logger.info(msg)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_handler(f"[{ts}] {msg}")

    @abstractmethod
    def connect(self, oauth_result: OAuthResult, client_config: Optional[Dict] = None) -> Account:
        ...

    def disconnect(self, account: Account) -> bool:
        if account.credential_ref:
            self.credential_store.delete("savesync", account.credential_ref)
        return True

    @abstractmethod
    def status(self, account: Account) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def test(self, account: Account) -> str:
        ...

    @abstractmethod
    def upload(self, src: str, dest_rel: str,
               progress_callback: Optional[Callable] = None) -> bool:
        ...

    @abstractmethod
    def download(self, dest: str, src_rel: str,
                 progress_callback: Optional[Callable] = None) -> bool:
        ...

    @abstractmethod
    def list_files(self, prefix: str = "") -> List[str]:
        ...

    def load_tokens(self, account: Account) -> Optional[Dict[str, Any]]:
        if not account.credential_ref:
            return None
        raw = self.credential_store.get("savesync", account.credential_ref)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    def save_tokens(self, account: Account, tokens: Dict[str, Any]) -> None:
        ref = account.credential_ref or f"acct_{uuid.uuid4().hex[:12]}"
        account.credential_ref = ref
        self.credential_store.store("savesync", ref, json.dumps(tokens))

    def build_oauth_url(self, client_config: Dict[str, Any], redirect_uri: str,
                        state: str, code_verifier: str) -> str:
        raise NotImplementedError

    def exchange_code(self, client_config: Dict[str, Any], redirect_uri: str,
                      code: str, code_verifier: str) -> OAuthResult:
        raise NotImplementedError

    def refresh_access_token(self, account: Account) -> Optional[str]:
        raise NotImplementedError


class LocalAdapter(ProviderAdapter):
    name = "local"
    display_name = "Local Folder"
    capabilities = ["upload", "download", "list"]
    needs_client_config = False

    def __init__(self, dest_root: Optional[str] = None):
        super().__init__()
        self.dest_root = dest_root or os.path.expanduser("~/SaveSyncBackup")
        self._account_override: Optional[Account] = None

    def connect(self, oauth_result: OAuthResult,
                client_config: Optional[Dict] = None) -> Account:
        path = client_config.get("path", self.dest_root) if client_config else self.dest_root
        safe_path = path.replace("/", "_").replace("\\", "_")
        acct = Account(
            provider="local",
            account_id=f"local_{safe_path}",
            display_email="",
            display_name=f"Local: {path}",
            capabilities=["upload", "download", "list"],
            credential_ref="",
            connected_at=datetime.now(timezone.utc).isoformat(),
            provider_config={"path": path},
        )
        self._account = acct
        self.dest_root = path
        os.makedirs(path, exist_ok=True)
        return acct

    def status(self, account: Account) -> Tuple[bool, str]:
        path = account.provider_config.get("path", self.dest_root)
        ok = os.path.isdir(path) and os.access(path, os.W_OK)
        return ok, "writable" if ok else "not writable"

    def test(self, account: Account) -> str:
        path = account.provider_config.get("path", self.dest_root)
        if os.access(path, os.W_OK):
            return f"OK (writable: {path})"
        return f"ERROR: not writable: {path}"

    def _sha256(self, path: str) -> str:
        import hashlib
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def upload(self, src: str, dest_rel: str,
               progress_callback: Optional[Callable] = None) -> bool:
        dst = os.path.join(self.dest_root, dest_rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src_size = os.path.getsize(src)
            fname = os.path.basename(src)
            tm = TransferManager()
            src_hash = tm.checksum(src)
            with open(src, "rb") as src_f:
                with open(dst, "wb") as dst_f:
                    bdone = 0
                    while True:
                        chunk = src_f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        dst_f.write(chunk)
                        bdone += len(chunk)
                        if progress_callback:
                            progress_callback(bdone, src_size, fname)
            dst_hash = tm.checksum(dst)
            if src_hash and dst_hash and src_hash != dst_hash:
                self.log(f"VERIFY FAILED: {os.path.basename(src)} mismatched after copy")
                return False
            os.utime(dst, None)
            self.log(f"Copied: {os.path.basename(src)}")
            if self.logging:
                self.logging.fs.modified(src, os.path.getsize(src))
            return True
        except Exception as e:
            self.log(f"Copy failed: {e}")
            if self.logging:
                self.logging.errors.capture("local_upload", e)
            return False

    def download(self, dest: str, src_rel: str,
                 progress_callback: Optional[Callable] = None) -> bool:
        src_path = os.path.join(self.dest_root, src_rel)
        if not os.path.exists(src_path):
            return False
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src_size = os.path.getsize(src_path)
            with open(src_path, "rb") as src_f:
                with open(dest, "wb") as dest_f:
                    bdone = 0
                    while True:
                        chunk = src_f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        dest_f.write(chunk)
                        bdone += len(chunk)
                        if progress_callback:
                            progress_callback(bdone, src_size, src_rel)
            return True
        except Exception as e:
            self.log(f"Download failed: {e}")
            if self.logging:
                self.logging.errors.capture("local_download", e)
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        results = []
        for root, _dirs, files in os.walk(self.dest_root):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), self.dest_root)
                if rel.startswith(prefix):
                    results.append(rel)
        return results

    def refresh_access_token(self, account: Account) -> Optional[str]:
        return None


class DropboxAdapter(ProviderAdapter):
    name = "dropbox"
    display_name = "Dropbox"
    capabilities = ["upload", "download", "list"]
    needs_client_config = True
    client_config_label = "Dropbox App Key"
    client_config_hint = "Create an app at https://www.dropbox.com/developers/apps"

    DROPBOX_AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
    DROPBOX_TOKEN_URL = "https://api.dropbox.com/oauth2/token"
    SCOPES = ["files.content.write", "files.content.read", "account_info.read"]

    def __init__(self, remote_root: str = "/SaveSync"):
        super().__init__()
        self.remote_root = remote_root
        self._client = None
        self._root_ensured = False

    INVALID_CHARS = str.maketrans({c: "_" for c in '#%{}~&:*?"<>|'})

    def _sanitize(self, path: str) -> str:
        path = path.replace("\\", "/")
        path = path.translate(self.INVALID_CHARS)
        parts = [p for p in path.split("/") if p]
        return "/" + "/".join(parts)

    def _ensure_remote_root(self):
        if self._root_ensured:
            return
        try:
            dbx = self._get_client()
            dbx.files_create_folder_v2(self.remote_root)
        except Exception:
            print("Dropbox ensure_remote_root: folder may already exist", file=sys.stderr)
        self._root_ensured = True

    def _get_client(self, token: Optional[str] = None):
        try:
            import dropbox
            if token:
                return dropbox.Dropbox(token)
            if self._client is None:
                return None
            return self._client
        except ImportError:
            return None

    def _remote_path(self, rel: str) -> str:
        safe_rel = self._sanitize(rel)
        return f"{self.remote_root}/{safe_rel}".replace("//", "/")

    def build_oauth_url(self, client_config: Dict[str, Any], redirect_uri: str,
                        state: str, code_verifier: str) -> str:
        app_key = client_config.get("app_key", "")
        params = f"client_id={app_key}&response_type=code&redirect_uri={redirect_uri}&state={state}"
        scopes = " ".join(self.SCOPES)
        params += f"&scope={scopes}&token_access_type=offline"
        return f"{self.DROPBOX_AUTHORIZE_URL}?{params}"

    def exchange_code(self, client_config: Dict[str, Any], redirect_uri: str,
                      code: str, code_verifier: str) -> OAuthResult:
        import urllib.request
        import urllib.parse
        app_key = client_config.get("app_key", "")
        app_secret = client_config.get("app_secret", "")
        data = urllib.parse.urlencode({
            "code": code,
            "grant_type": "authorization_code",
            "client_id": app_key,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
        }).encode()
        req = urllib.request.Request(self.DROPBOX_TOKEN_URL, data=data,
                                     method="POST")
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode())
        return OAuthResult(
            access_token=body.get("access_token", ""),
            refresh_token=body.get("refresh_token", ""),
            expires_at=time.time() + body.get("expires_in", 14400),
            account_id=body.get("account_id", ""),
            display_email=body.get("account_id", ""),
            display_name="Dropbox",
        )

    def _ensure_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens:
            return None
        token = tokens.get("access_token", "")
        if not token:
            return None
        return token

    def connect(self, oauth_result: OAuthResult,
                client_config: Optional[Dict] = None) -> Account:
        account_id = oauth_result.account_id or uuid.uuid4().hex[:12]
        acct = Account(
            provider="dropbox",
            account_id=account_id,
            display_email=oauth_result.display_email,
            display_name=oauth_result.display_name or "Dropbox",
            capabilities=self.capabilities,
            credential_ref="",
            connected_at=datetime.now(timezone.utc).isoformat(),
            provider_config={"remote_root": self.remote_root},
        )
        self.save_tokens(acct, {
            "access_token": oauth_result.access_token,
            "refresh_token": oauth_result.refresh_token,
            "expires_at": oauth_result.expires_at,
            "token_type": "bearer",
        })
        self._client = self._get_client(oauth_result.access_token)
        self._account = acct
        return acct

    def disconnect(self, account: Account) -> bool:
        token = self._ensure_token(account)
        if token:
            try:
                import urllib.request
                import urllib.parse
                data = urllib.parse.urlencode({"access_token": token}).encode()
                req = urllib.request.Request(
                    "https://api.dropbox.com/2/auth/token/revoke",
                    data=data, method="POST")
                urllib.request.urlopen(req)
            except Exception:
                print("Dropbox token revoke failed", file=sys.stderr)
        return super().disconnect(account)
        
    def status(self, account: Account) -> Tuple[bool, str]:
        token = self._ensure_token(account)
        if not token:
            return False, "no token"
        try:
            import dropbox
            dbx = dropbox.Dropbox(token)
            dbx.users_get_current_account()
            return True, "connected"
        except ImportError:
            return False, "SDK not installed"
        except Exception as e:
            return False, str(e)

    def test(self, account: Account) -> str:
        token = self._ensure_token(account)
        if not token:
            return "ERROR: no token stored"
        try:
            import dropbox
            dbx = dropbox.Dropbox(token)
            acc = dbx.users_get_current_account()
            email = getattr(acc, "email", "?")
            return f"OK ({email})"
        except ImportError:
            return "Dropbox SDK not installed"
        except Exception as e:
            return f"ERROR: {e}"

    def _upload_session(self, src: str, remote_path: str,
                         progress_callback: Optional[Callable] = None) -> bool:
        import dropbox
        dbx = self._get_client(None)
        src_size = os.path.getsize(src)
        fname = os.path.basename(src)
        if src_size <= CHUNK_SIZE:
            with open(src, "rb") as f:
                dbx.files_upload(f.read(), remote_path,
                                 mode=dropbox.files.WriteMode.overwrite)
            if progress_callback:
                progress_callback(src_size, src_size, fname)
            return True
        session = dbx.files_upload_session_start(b"")
        cursor = dropbox.files.UploadSessionCursor(
            session_id=session.session_id, offset=0)
        commit = dropbox.files.CommitInfo(
            path=remote_path, mode=dropbox.files.WriteMode.overwrite)
        with open(src, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                if cursor.offset + len(chunk) >= src_size:
                    dbx.files_upload_session_finish(chunk, cursor, commit)
                    if progress_callback:
                        progress_callback(src_size, src_size, fname)
                    break
                dbx.files_upload_session_append_v2(chunk, cursor)
                cursor.offset += len(chunk)
                if progress_callback:
                    progress_callback(cursor.offset, src_size, fname)
        return True

    def upload(self, src: str, dest_rel: str,
               progress_callback: Optional[Callable] = None) -> bool:
        token = self._ensure_token(self._account) if self._account else None
        if not token:
            return False
        try:
            import dropbox
            self._ensure_remote_root()
            remote_path = self._remote_path(dest_rel)
            ok = self._upload_session(src, remote_path, progress_callback)
            if ok:
                self.log(f"Uploaded: {os.path.basename(src)}")
                if self.logging:
                    self.logging.fs.modified(src, os.path.getsize(src))
            return ok
        except ImportError:
            self.log("dropbox SDK not installed")
            return False
        except Exception as e:
            self.log(f"Dropbox upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_upload", e)
            return False

    def download(self, dest: str, src_rel: str,
                 progress_callback: Optional[Callable] = None) -> bool:
        token = self._ensure_token(self._account) if self._account else None
        if not token:
            return False
        try:
            dbx = self._get_client(token)
            remote_path = self._remote_path(src_rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            dbx.files_download_to_file(dest, remote_path)
            if progress_callback:
                try:
                    fsize = os.path.getsize(dest)
                    progress_callback(fsize, fsize, src_rel)
                except OSError:
                    progress_callback(1, 1, src_rel)
            return True
        except ImportError:
            return False
        except Exception as e:
            self.log(f"Dropbox download failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_download", e)
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        token = self._ensure_token(self._account) if self._account else None
        if not token:
            return []
        try:
            import dropbox
            from dropbox.files import FileMetadata
            self._ensure_remote_root()
            dbx = self._get_client(token)
            remote_path = self._remote_path(prefix)
            if remote_path == self.remote_root.rstrip("/"):
                remote_path = self.remote_root
            results = []
            try:
                resp = dbx.files_list_folder(remote_path)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.ListFolderError):
                    if e.error.reason.is_not_found:
                        return []
                raise
            for entry in resp.entries:
                if isinstance(entry, FileMetadata):
                    rel = entry.path_display[len(self.remote_root) + 1:]
                    results.append(rel)
            while resp.has_more:
                resp = dbx.files_list_folder_continue(resp.cursor)
                for entry in resp.entries:
                    if isinstance(entry, FileMetadata):
                        rel = entry.path_display[len(self.remote_root) + 1:]
                        results.append(rel)
            return results
        except ImportError:
            return []
        except Exception as e:
            self.log(f"Dropbox list failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_list", e)
            return []

    def refresh_access_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens or not tokens.get("refresh_token"):
            return None
        import urllib.request
        import urllib.parse
        client_config = account.provider_config
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_config.get("app_key", ""),
            "client_secret": client_config.get("app_secret", ""),
        }).encode()
        req = urllib.request.Request(self.DROPBOX_TOKEN_URL, data=data,
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req)
            body = json.loads(resp.read().decode())
            tokens["access_token"] = body["access_token"]
            tokens["expires_at"] = time.time() + body.get("expires_in", 14400)
            self.save_tokens(account, tokens)
            return body["access_token"]
        except Exception:
            return None


class GoogleDriveAdapter(ProviderAdapter):
    name = "google_drive"
    display_name = "Google Drive"
    capabilities = ["upload", "download", "list"]
    needs_client_config = True
    client_config_label = "Google Desktop OAuth Client JSON"
    client_config_hint = "Download from Google Cloud Console → APIs & Services → Credentials"

    GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = [
        "https://www.googleapis.com/auth/drive.appdata",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(self):
        super().__init__()
        self._service = None
        self._current_account: Optional[Account] = None

    def _get_service(self, token: str):
        if self._service is not None:
            return self._service
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(token=token, scopes=self.SCOPES)
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _parse_client_config(self, client_config: Dict[str, Any]) -> Tuple[str, str]:
        client_id = client_config.get("installed", client_config).get("client_id", "")
        client_secret = client_config.get("installed", client_config).get("client_secret", "")
        return client_id, client_secret

    def build_oauth_url(self, client_config: Dict[str, Any], redirect_uri: str,
                        state: str, code_verifier: str) -> str:
        client_id, _ = self._parse_client_config(client_config)
        params = (
            f"client_id={client_id}&redirect_uri={redirect_uri}"
            f"&response_type=code&scope={' '.join(self.SCOPES)}"
            f"&state={state}&access_type=offline&prompt=consent"
        )
        return f"{self.GOOGLE_AUTHORIZE_URL}?{params}"

    def exchange_code(self, client_config: Dict[str, Any], redirect_uri: str,
                      code: str, code_verifier: str) -> OAuthResult:
        import urllib.request
        import urllib.parse
        client_id, client_secret = self._parse_client_config(client_config)
        data = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode()
        req = urllib.request.Request(self.GOOGLE_TOKEN_URL, data=data,
                                     method="POST")
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode())
        return OAuthResult(
            access_token=body.get("access_token", ""),
            refresh_token=body.get("refresh_token", ""),
            expires_at=time.time() + body.get("expires_in", 3600),
            extra={"id_token": body.get("id_token", "")},
        )

    def _fetch_user_info(self, token: str) -> Tuple[str, str, str]:
        import urllib.request
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"})
        resp = urllib.request.urlopen(req)
        info = json.loads(resp.read().decode())
        return (
            info.get("id", ""),
            info.get("email", ""),
            info.get("name", ""),
        )

    def connect(self, oauth_result: OAuthResult,
                client_config: Optional[Dict] = None) -> Account:
        account_id = oauth_result.account_id
        display_email = oauth_result.display_email
        display_name = oauth_result.display_name
        if not account_id and oauth_result.access_token:
            try:
                account_id, display_email, display_name = self._fetch_user_info(
                    oauth_result.access_token)
            except Exception:
                account_id = uuid.uuid4().hex[:12]
        acct = Account(
            provider="google_drive",
            account_id=account_id or uuid.uuid4().hex[:12],
            display_email=display_email,
            display_name=display_name or "Google Drive",
            capabilities=self.capabilities,
            credential_ref="",
            connected_at=datetime.now(timezone.utc).isoformat(),
            provider_config={"folder_type": "appDataFolder"},
        )
        self.save_tokens(acct, {
            "access_token": oauth_result.access_token,
            "refresh_token": oauth_result.refresh_token,
            "expires_at": oauth_result.expires_at,
            "scopes": self.SCOPES,
        })
        self._current_account = acct
        return acct

    def disconnect(self, account: Account) -> bool:
        token = self._ensure_token(account)
        if token:
            try:
                import urllib.request
                import urllib.parse
                data = urllib.parse.urlencode({"token": token}).encode()
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/revoke",
                    data=data, method="POST")
                urllib.request.urlopen(req)
            except Exception:
                print("Google Drive token revoke during disconnect failed", file=sys.stderr)
        return super().disconnect(account)

    def _ensure_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens:
            return None
        token = tokens.get("access_token", "")
        expires_at = tokens.get("expires_at", 0)
        if time.time() >= expires_at and tokens.get("refresh_token"):
            token = self.refresh_access_token(account) or token
        return token or None

    def status(self, account: Account) -> Tuple[bool, str]:
        token = self._ensure_token(account)
        if not token:
            return False, "no token"
        try:
            service = self._get_service(token)
            about = service.about().get(fields="user").execute()
            email = about.get("user", {}).get("emailAddress", "?")
            return True, f"connected as {email}"
        except ImportError:
            return False, "google-api-python-client not installed"
        except Exception as e:
            return False, str(e)

    def test(self, account: Account) -> str:
        token = self._ensure_token(account)
        if not token:
            return "ERROR: no token stored"
        try:
            service = self._get_service(token)
            about = service.about().get(fields="user").execute()
            email = about.get("user", {}).get("emailAddress", "?")
            return f"OK ({email})"
        except ImportError:
            return "google-api-python-client not installed"
        except Exception as e:
            return f"ERROR: {e}"

    def upload(self, src: str, dest_rel: str,
               progress_callback: Optional[Callable] = None) -> bool:
        if not self._current_account:
            return False
        token = self._ensure_token(self._current_account)
        if not token:
            return False
        try:
            service = self._get_service(token)
            file_name = os.path.basename(dest_rel)
            from googleapiclient.http import MediaFileUpload
            parent_folder = self._ensure_app_folder(service, token)
            media = MediaFileUpload(src, resumable=True, chunksize=CHUNK_SIZE)
            request = service.files().create(
                body={"name": file_name, "parents": [parent_folder]},
                media_body=media,
                fields="id",
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status and progress_callback:
                    progress_callback(status.progress(), status.total(), file_name)
            if progress_callback:
                try:
                    fsize = os.path.getsize(src)
                    progress_callback(fsize, fsize, file_name)
                except OSError:
                    pass
            self.log(f"Uploaded: {file_name}")
            if self.logging:
                self.logging.fs.modified(src, os.path.getsize(src))
            return True
        except ImportError:
            self.log("google-api-python-client not installed")
            return False
        except Exception as e:
            self.log(f"Drive upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("drive_upload", e)
            return False

    def _ensure_app_folder(self, service, token: str) -> str:
        query = "name='SaveSync' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, spaces="appDataFolder",
                                       pageSize=1).execute()
        items = results.get("files", [])
        if items:
            return items[0]["id"]
        file_meta = {
            "name": "SaveSync",
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(
            body=file_meta, fields="id",
        ).execute()
        return folder["id"]

    def download(self, dest: str, src_rel: str,
                 progress_callback: Optional[Callable] = None) -> bool:
        if not self._current_account:
            return False
        token = self._ensure_token(self._current_account)
        if not token:
            return False
        try:
            service = self._get_service(token)
            parent = self._ensure_app_folder(service, token)
            file_name = os.path.basename(src_rel)
            query = f"name='{file_name}' and '{parent}' in parents and trashed=false"
            results = service.files().list(q=query, pageSize=1,
                                           fields="files(id)").execute()
            items = results.get("files", [])
            if not items:
                return False
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            from googleapiclient.http import MediaIoBaseDownload
            import io
            request = service.files().get_media(fileId=items[0]["id"])
            fh = io.FileIO(dest, "wb")
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                progress, done = downloader.next_chunk()
                if progress and progress_callback:
                    progress_callback(progress.progress(), progress.total(), file_name)
            if progress_callback:
                try:
                    fsize = os.path.getsize(dest)
                    progress_callback(fsize, fsize, file_name)
                except OSError:
                    pass
            return True
        except ImportError:
            return False
        except Exception as e:
            self.log(f"Drive download failed: {e}")
            if self.logging:
                self.logging.errors.capture("drive_download", e)
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        if not self._current_account:
            return []
        token = self._ensure_token(self._current_account)
        if not token:
            return []
        try:
            service = self._get_service(token)
            parent = self._ensure_app_folder(service, token)
            results = []
            page_token = None
            while True:
                q = f"'{parent}' in parents and trashed=false"
                if prefix:
                    q += f" and name contains '{prefix}'"
                resp = service.files().list(
                    q=q, spaces="drive",
                    fields="nextPageToken, files(name, id)",
                    pageToken=page_token, pageSize=200,
                ).execute()
                for f in resp.get("files", []):
                    results.append(f["name"])
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            return results
        except ImportError:
            return []
        except Exception as e:
            self.log(f"Drive list failed: {e}")
            if self.logging:
                self.logging.errors.capture("drive_list", e)
            return []

    def refresh_access_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens or not tokens.get("refresh_token"):
            return None
        import urllib.request
        import urllib.parse
        client_config = account.provider_config
        client_id = client_config.get("client_id", "")
        client_secret = client_config.get("client_secret", "")
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()
        req = urllib.request.Request(self.GOOGLE_TOKEN_URL, data=data,
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req)
            body = json.loads(resp.read().decode())
            tokens["access_token"] = body["access_token"]
            tokens["expires_at"] = time.time() + body.get("expires_in", 3600)
            self.save_tokens(account, tokens)
            return body["access_token"]
        except Exception:
            return None


class OneDriveAdapter(ProviderAdapter):
    name = "onedrive"
    display_name = "OneDrive"
    capabilities = ["upload", "download", "list"]
    needs_client_config = True
    client_config_label = "OneDrive Application (Client) ID"
    client_config_hint = "Register an app at https://portal.azure.com → App registrations"

    ONEDRIVE_AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    ONEDRIVE_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    SCOPES = ["Files.ReadWrite.AppFolder", "offline_access"]

    def __init__(self):
        super().__init__()
        self._current_account: Optional[Account] = None

    def build_oauth_url(self, client_config: Dict[str, Any], redirect_uri: str,
                        state: str, code_verifier: str) -> str:
        client_id = client_config.get("client_id", "")
        params = (
            f"client_id={client_id}&redirect_uri={redirect_uri}"
            f"&response_type=code&scope={' '.join(self.SCOPES)}"
            f"&state={state}&prompt=select_account"
        )
        return f"{self.ONEDRIVE_AUTHORIZE_URL}?{params}"

    def exchange_code(self, client_config: Dict[str, Any], redirect_uri: str,
                      code: str, code_verifier: str) -> OAuthResult:
        import urllib.request
        import urllib.parse
        client_id = client_config.get("client_id", "")
        client_secret = client_config.get("client_secret", "")
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode()
        req = urllib.request.Request(self.ONEDRIVE_TOKEN_URL, data=data,
                                     method="POST")
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode())
        return OAuthResult(
            access_token=body.get("access_token", ""),
            refresh_token=body.get("refresh_token", ""),
            expires_at=time.time() + body.get("expires_in", 3600),
        )

    def _fetch_user_info(self, token: str) -> Tuple[str, str, str]:
        import urllib.request
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token}"})
        resp = urllib.request.urlopen(req)
        info = json.loads(resp.read().decode())
        return (
            info.get("id", ""),
            info.get("userPrincipalName", info.get("mail", "")),
            info.get("displayName", ""),
        )

    def _ensure_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens:
            return None
        token = tokens.get("access_token", "")
        expires_at = tokens.get("expires_at", 0)
        if time.time() >= expires_at and tokens.get("refresh_token"):
            token = self.refresh_access_token(account) or token
        return token or None

    def connect(self, oauth_result: OAuthResult,
                client_config: Optional[Dict] = None) -> Account:
        account_id = oauth_result.account_id
        display_email = oauth_result.display_email
        display_name = oauth_result.display_name
        if not account_id and oauth_result.access_token:
            try:
                account_id, display_email, display_name = self._fetch_user_info(
                    oauth_result.access_token)
            except Exception:
                account_id = uuid.uuid4().hex[:12]
        acct = Account(
            provider="onedrive",
            account_id=account_id or uuid.uuid4().hex[:12],
            display_email=display_email,
            display_name=display_name or "OneDrive",
            capabilities=self.capabilities,
            credential_ref="",
            connected_at=datetime.now(timezone.utc).isoformat(),
            provider_config={},
        )
        self.save_tokens(acct, {
            "access_token": oauth_result.access_token,
            "refresh_token": oauth_result.refresh_token,
            "expires_at": oauth_result.expires_at,
            "scopes": self.SCOPES,
        })
        self._current_account = acct
        return acct

    def disconnect(self, account: Account) -> bool:
        token = self._ensure_token(account)
        if token:
            try:
                import urllib.request
                data = urllib.parse.urlencode({"token": token}).encode()
                req = urllib.request.Request(
                    "https://login.microsoftonline.com/common/oauth2/v2.0/logout",
                    data=data, method="POST")
                urllib.request.urlopen(req)
            except Exception:
                print("OneDrive logout request failed", file=sys.stderr)
        return super().disconnect(account)

    def status(self, account: Account) -> Tuple[bool, str]:
        token = self._ensure_token(account)
        if not token:
            return False, "no token"
        try:
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me/drive",
                headers={"Authorization": f"Bearer {token}"})
            resp = urllib.request.urlopen(req)
            info = json.loads(resp.read().decode())
            return True, f"connected ({info.get('id', '?')[:8]}...)"
        except Exception as e:
            return False, str(e)

    def test(self, account: Account) -> str:
        token = self._ensure_token(account)
        if not token:
            return "ERROR: no token stored"
        try:
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {token}"})
            resp = urllib.request.urlopen(req)
            info = json.loads(resp.read().decode())
            return f"OK ({info.get('userPrincipalName', info.get('displayName', '?'))})"
        except Exception as e:
            return f"ERROR: {e}"

    def _get_app_folder_id(self, token: str) -> Optional[str]:
        import urllib.request
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me/drive/special/approot",
            headers={"Authorization": f"Bearer {token}"})
        resp = urllib.request.urlopen(req)
        info = json.loads(resp.read().decode())
        return info.get("id")

    def _upload_session_onedrive(self, src: str, file_name: str,
                                  folder_id: str, token: str,
                                  progress_callback: Optional[Callable] = None) -> bool:
        import urllib.request
        src_size = os.path.getsize(src)
        session_url = (
            f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"
            f":/{file_name}:/createUploadSession"
        )
        req = urllib.request.Request(
            session_url, data=b"{}", method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req)
        session = json.loads(resp.read().decode())
        upload_url = session.get("uploadUrl")
        if not upload_url:
            return False
        with open(src, "rb") as f:
            offset = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                chunk_len = len(chunk)
                content_range = f"bytes {offset}-{offset + chunk_len - 1}/{src_size}"
                put_req = urllib.request.Request(
                    upload_url, data=chunk, method="PUT")
                put_req.add_header("Content-Range", content_range)
                resp = urllib.request.urlopen(put_req)
                offset += chunk_len
                if progress_callback:
                    progress_callback(offset, src_size, file_name)
        return True

    def upload(self, src: str, dest_rel: str,
               progress_callback: Optional[Callable] = None) -> bool:
        if not self._current_account:
            return False
        token = self._ensure_token(self._current_account)
        if not token:
            return False
        try:
            file_name = os.path.basename(dest_rel)
            folder_id = self._get_app_folder_id(token)
            ok = self._upload_session_onedrive(src, file_name, folder_id,
                                                token, progress_callback)
            if ok:
                self.log(f"Uploaded: {file_name}")
                if self.logging:
                    self.logging.fs.modified(src, os.path.getsize(src))
            return ok
        except Exception as e:
            self.log(f"OneDrive upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_upload", e)
            return False

    def download(self, dest: str, src_rel: str,
                 progress_callback: Optional[Callable] = None) -> bool:
        if not self._current_account:
            return False
        token = self._ensure_token(self._current_account)
        if not token:
            return False
        try:
            file_name = os.path.basename(src_rel)
            folder_id = self._get_app_folder_id(token)
            req = urllib.request.Request(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"
                f":/{file_name}:/content",
                headers={"Authorization": f"Bearer {token}"})
            resp = urllib.request.urlopen(req)
            content_len = int(resp.headers.get("Content-Length", 0))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            bdone = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    bdone += len(chunk)
                    if progress_callback and content_len > 0:
                        progress_callback(bdone, content_len, file_name)
            if progress_callback and content_len > 0:
                progress_callback(bdone, bdone, file_name)
            return True
        except Exception as e:
            self.log(f"OneDrive download failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_download", e)
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        if not self._current_account:
            return []
        token = self._ensure_token(self._current_account)
        if not token:
            return []
        try:
            folder_id = self._get_app_folder_id(token)
            req = urllib.request.Request(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children",
                headers={"Authorization": f"Bearer {token}"})
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read().decode())
            return [item.get("name", "") for item in data.get("value", [])]
        except Exception as e:
            self.log(f"OneDrive list failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_list", e)
            return []

    def refresh_access_token(self, account: Account) -> Optional[str]:
        tokens = self.load_tokens(account)
        if not tokens or not tokens.get("refresh_token"):
            return None
        import urllib.request
        import urllib.parse
        client_config = account.provider_config
        client_id = client_config.get("client_id", "")
        client_secret = client_config.get("client_secret", "")
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": " ".join(self.SCOPES),
        }).encode()
        req = urllib.request.Request(self.ONEDRIVE_TOKEN_URL, data=data,
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req)
            body = json.loads(resp.read().decode())
            tokens["access_token"] = body["access_token"]
            tokens["expires_at"] = time.time() + body.get("expires_in", 3600)
            self.save_tokens(account, tokens)
            return body["access_token"]
        except Exception:
            return None


class ProviderRegistry:
    def __init__(self):
        self._adapters: Dict[str, Type[ProviderAdapter]] = {}
        self._instances: Dict[str, ProviderAdapter] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register("local", LocalAdapter)
        self.register("dropbox", DropboxAdapter)
        self.register("google_drive", GoogleDriveAdapter)
        self.register("onedrive", OneDriveAdapter)

    def register(self, name: str, adapter_cls: Type[ProviderAdapter]):
        self._adapters[name] = adapter_cls

    def get(self, name: str) -> Optional[Type[ProviderAdapter]]:
        return self._adapters.get(name)

    def get_instance(self, name: str) -> Optional[ProviderAdapter]:
        if name not in self._instances:
            cls = self.get(name)
            if cls:
                self._instances[name] = cls()
        return self._instances.get(name)

    def get_instance_for_account(self, account: Account) -> Optional[ProviderAdapter]:
        inst = self.get_instance(account.provider)
        if inst:
            inst._account = account
        return inst

    def list_providers(self) -> List[Dict[str, Any]]:
        result = []
        for name, cls in self._adapters.items():
            result.append({
                "name": name,
                "display_name": cls.display_name,
                "capabilities": cls.capabilities,
                "needs_client_config": cls.needs_client_config,
                "client_config_label": cls.client_config_label,
                "client_config_hint": cls.client_config_hint,
            })
        return result


_registry: Optional[ProviderRegistry] = None
_registry_lock = threading.Lock()


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ProviderRegistry()
    return _registry


def create_adapter_from_config(config: dict, credential_store: Optional[CredentialStore] = None) -> ProviderAdapter:
    kind = config.get("type", "local")
    registry = get_provider_registry()
    inst = registry.get_instance(kind)
    if not inst:
        raise ValueError(f"Unknown provider: {kind}")
    if kind == "local":
        inst.dest_root = config.get("path", os.path.expanduser("~/SaveSyncBackup"))
    return inst
