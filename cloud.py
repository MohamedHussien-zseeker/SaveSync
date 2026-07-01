#!/usr/bin/env python3
import os
import shutil
from datetime import datetime
import sys
from typing import Optional


class CloudProvider:
    name = "local"

    def __init__(self):
        self.log_handler = print
        self.logger = None
        self.logging = None

    def log(self, msg: str):
        if self.logger:
            self.logger.info(msg)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_handler(f"[{ts}] {msg}")

    def upload(self, src: str, dest_rel: str, progress_callback=None) -> bool:
        raise NotImplementedError

    def download(self, dest: str, src_rel: str, progress_callback=None) -> bool:
        raise NotImplementedError

    def list_files(self, prefix: str = "") -> list:
        raise NotImplementedError

    def test(self) -> str:
        raise NotImplementedError


class LocalFolder(CloudProvider):
    name = "Local Folder"

    def __init__(self, dest_root: str):
        super().__init__()
        self.dest_root = dest_root
        os.makedirs(self.dest_root, exist_ok=True)

    def upload(self, src: str, dest_rel: str, progress_callback=None) -> bool:
        dst = os.path.join(self.dest_root, dest_rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src_size = os.path.getsize(src)
            fname = os.path.basename(src)
            with open(src, "rb") as src_f:
                with open(dst, "wb") as dst_f:
                    bdone = 0
                    while True:
                        chunk = src_f.read(8388608)
                        if not chunk:
                            break
                        dst_f.write(chunk)
                        bdone += len(chunk)
                        if progress_callback:
                            progress_callback(bdone, src_size, fname)
            self.log(f"Copied: {os.path.basename(src)}")
            if self.logging:
                self.logging.fs.modified(src, os.path.getsize(src))
            return True
        except Exception as e:
            self.log(f"Copy failed: {e}")
            if self.logging:
                self.logging.errors.capture("local_upload", e)
            return False

    def download(self, dest: str, src_rel: str, progress_callback=None) -> bool:
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
                        chunk = src_f.read(8388608)
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

    def list_files(self, prefix: str = "") -> list:
        results = []
        for root, _dirs, files in os.walk(self.dest_root):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), self.dest_root)
                if rel.startswith(prefix):
                    results.append(rel)
        return results

    def test(self) -> str:
        if os.access(self.dest_root, os.W_OK):
            return f"OK (writable: {self.dest_root})"
        return f"ERROR: not writable: {self.dest_root}"


INVALID_DROPBOX_CHARS = str.maketrans(
    {c: "_" for c in '#%{}~&:*?"<>|'}
)


class DropboxProvider(CloudProvider):
    name = "Dropbox"

    def __init__(self, token: str, remote_root: str = "/SaveSync"):
        super().__init__()
        self.token = token
        self.remote_root = remote_root
        self._client = None
        self._root_ensured = False

    def _sanitize(self, path: str) -> str:
        path = path.replace("\\", "/")
        path = path.translate(INVALID_DROPBOX_CHARS)
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

    def _get_client(self):
        if self._client is None:
            try:
                import dropbox
                self._client = dropbox.Dropbox(self.token)
            except ImportError:
                return None
        return self._client

    def _remote_path(self, rel: str) -> str:
        safe_rel = self._sanitize(rel)
        return f"{self.remote_root}/{safe_rel}".replace("//", "/")

    def upload(self, src: str, dest_rel: str, progress_callback=None) -> bool:
        try:
            import dropbox
            self._ensure_remote_root()
            dbx = self._get_client()
            remote_path = self._remote_path(dest_rel)
            fsize = os.path.getsize(src)
            fname = os.path.basename(src)
            with open(src, "rb") as f:
                dbx.files_upload(f.read(), remote_path, mode=dropbox.files.WriteMode.overwrite)
            if progress_callback:
                progress_callback(fsize, fsize, fname)
            self.log(f"Uploaded: {os.path.basename(src)}")
            if self.logging:
                self.logging.fs.modified(src, fsize)
            return True
        except ImportError:
            self.log("dropbox SDK not installed: pip install dropbox")
            return False
        except Exception as e:
            self.log(f"Dropbox upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_upload", e)
            return False

    def download(self, dest: str, src_rel: str, progress_callback=None) -> bool:
        try:
            dbx = self._get_client()
            remote_path = self._remote_path(src_rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            dbx.files_download_to_file(dest, remote_path)
            if progress_callback:
                dst_size = os.path.getsize(dest)
                progress_callback(dst_size, dst_size, src_rel)
            return True
        except ImportError:
            return False
        except Exception as e:
            self.log(f"Dropbox download failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_download", e)
            return False

    def list_files(self, prefix: str = "") -> list:
        try:
            import dropbox
            from dropbox.files import FileMetadata
            self._ensure_remote_root()
            dbx = self._get_client()
            remote_path = self._remote_path(prefix)
            if remote_path == self.remote_root.rstrip("/"):
                remote_path = self.remote_root
            results = []
            try:
                resp = dbx.files_list_folder(remote_path)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.ListFolderError) and \
                   isinstance(e.error.reason, dropbox.files.LookupError) and \
                   e.error.reason.is_not_found:
                    return []
                raise
            for entry in resp.entries:
                if isinstance(entry, FileMetadata):
                    rel = entry.path_display[len(self.remote_root)+1:]
                    results.append(rel)
            while resp.has_more:
                resp = dbx.files_list_folder_continue(resp.cursor)
                for entry in resp.entries:
                    if isinstance(entry, FileMetadata):
                        rel = entry.path_display[len(self.remote_root)+1:]
                        results.append(rel)
            return results
        except ImportError:
            return []
        except Exception as e:
            self.log(f"Dropbox list failed: {e}")
            if self.logging:
                self.logging.errors.capture("dropbox_list", e)
            return []

    def test(self) -> str:
        try:
            import dropbox
            dbx = self._get_client()
            dbx.users_get_current_account()
            return f"OK (user: {self.token[:8]}...) "
        except ImportError:
            return "Dropbox SDK not installed"
        except Exception as e:
            return f"ERROR: {e}"


class GoogleDriveProvider(CloudProvider):
    name = "Google Drive"

    def __init__(self, credentials_json: dict, folder_id: Optional[str] = None):
        super().__init__()
        self.credentials = credentials_json
        self.folder_id = folder_id
        self._service = None

    def _get_service(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds = Credentials.from_authorized_user_info(self.credentials)
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _ensure_folder(self) -> str:
        if self.folder_id:
            return self.folder_id
        service = self._get_service()
        query = "name='SaveSync' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, spaces="drive", pageSize=1).execute()
        items = results.get("files", [])
        if items:
            self.folder_id = items[0]["id"]
        else:
            file_meta = {"name": "SaveSync", "mimeType": "application/vnd.google-apps.folder"}
            folder = service.files().create(body=file_meta, fields="id").execute()
            self.folder_id = folder["id"]
        return self.folder_id

    def upload(self, src: str, dest_rel: str, progress_callback=None) -> bool:
        try:
            service = self._get_service()
            parent = self._ensure_folder()
            file_name = os.path.basename(dest_rel)
            from googleapiclient.http import MediaFileUpload
            media = MediaFileUpload(src, resumable=True)
            service.files().create(
                body={"name": file_name, "parents": [parent]},
                media_body=media,
                fields="id",
            ).execute()
            if progress_callback:
                fsize = os.path.getsize(src)
                progress_callback(fsize, fsize, file_name)
            self.log(f"Uploaded: {file_name}")
            if self.logging:
                self.logging.fs.modified(src, os.path.getsize(src))
            return True
        except ImportError:
            self.log("google-api-python-client not installed: pip install google-api-python-client")
            return False
        except Exception as e:
            self.log(f"Drive upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("drive_upload", e)
            return False

    def download(self, dest: str, src_rel: str, progress_callback=None) -> bool:
        try:
            service = self._get_service()
            parent = self._ensure_folder()
            file_name = os.path.basename(src_rel)
            query = f"name='{file_name}' and '{parent}' in parents and trashed=false"
            results = service.files().list(q=query, pageSize=1, fields="files(id)").execute()
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
                _, done = downloader.next_chunk()
            if progress_callback:
                dst_size = os.path.getsize(dest)
                progress_callback(dst_size, dst_size, file_name)
            return True
        except ImportError:
            return False
        except Exception as e:
            self.log(f"Drive download failed: {e}")
            if self.logging:
                self.logging.errors.capture("drive_download", e)
            return False

    def list_files(self, prefix: str = "") -> list:
        try:
            service = self._get_service()
            parent = self._ensure_folder()
            results = []
            page_token = None
            while True:
                q = f"'{parent}' in parents and trashed=false"
                if prefix:
                    q += f" and name contains '{prefix}'"
                resp = service.files().list(
                    q=q, spaces="drive", fields="nextPageToken, files(name, id)",
                    pageToken=page_token, pageSize=200
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

    def test(self) -> str:
        try:
            service = self._get_service()
            about = service.about().get(fields="user").execute()
            email = about.get("user", {}).get("emailAddress", "?")
            return f"OK ({email})"
        except ImportError:
            return "google-api-python-client not installed"
        except Exception as e:
            return f"ERROR: {e}"


class OneDriveProvider(CloudProvider):
    name = "OneDrive"

    def __init__(self, token: str = ""):
        super().__init__()
        self.token = token
        self._app_folder_id = None

    def _ensure_token(self) -> str:
        return self.token

    def _get_app_folder_id(self) -> str:
        if self._app_folder_id:
            return self._app_folder_id
        import urllib.request
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me/drive/special/approot",
            headers={"Authorization": f"Bearer {self.token}"})
        resp = urllib.request.urlopen(req)
        info = json.loads(resp.read().decode())
        self._app_folder_id = info["id"]
        return self._app_folder_id

    def upload(self, src: str, dest_rel: str, progress_callback=None) -> bool:
        try:
            file_name = os.path.basename(dest_rel)
            folder_id = self._get_app_folder_id()
            upload_url = (
                f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"
                f":/{file_name}:/content"
            )
            fsize = os.path.getsize(src)
            with open(src, "rb") as f:
                data = f.read()
            import urllib.request
            req = urllib.request.Request(upload_url, data=data, method="PUT")
            req.add_header("Authorization", f"Bearer {self.token}")
            urllib.request.urlopen(req)
            if progress_callback:
                progress_callback(fsize, fsize, file_name)
            self.log(f"Uploaded: {file_name}")
            if self.logging:
                self.logging.fs.modified(src, fsize)
            return True
        except ImportError:
            self.log("OneDrive requires urllib (stdlib)")
            return False
        except Exception as e:
            self.log(f"OneDrive upload failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_upload", e)
            return False

    def download(self, dest: str, src_rel: str, progress_callback=None) -> bool:
        try:
            file_name = os.path.basename(src_rel)
            folder_id = self._get_app_folder_id()
            import urllib.request
            req = urllib.request.Request(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"
                f":/{file_name}:/content",
                headers={"Authorization": f"Bearer {self.token}"})
            resp = urllib.request.urlopen(req)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(resp.read())
            if progress_callback:
                dst_size = os.path.getsize(dest)
                progress_callback(dst_size, dst_size, file_name)
            return True
        except Exception as e:
            self.log(f"OneDrive download failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_download", e)
            return False

    def list_files(self, prefix: str = "") -> list:
        try:
            folder_id = self._get_app_folder_id()
            import urllib.request
            req = urllib.request.Request(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children",
                headers={"Authorization": f"Bearer {self.token}"})
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read().decode())
            return [item.get("name", "") for item in data.get("value", [])]
        except Exception as e:
            self.log(f"OneDrive list failed: {e}")
            if self.logging:
                self.logging.errors.capture("onedrive_list", e)
            return []

    def test(self) -> str:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {self.token}"})
            resp = urllib.request.urlopen(req)
            info = json.loads(resp.read().decode())
            return f"OK ({info.get('userPrincipalName', info.get('displayName', '?'))})"
        except Exception as e:
            return f"ERROR: {e}"


def create_provider(config: dict) -> CloudProvider:
    kind = config.get("type", "local")
    if kind == "local":
        return LocalFolder(config.get("path", os.path.expanduser("~/SaveSyncBackup")))
    elif kind == "dropbox":
        token = config.get("token", "")
        if not token and "credential_ref" in config:
            from credential_store import get_credential_store
            store = get_credential_store()
            raw = store.get("savesync", config["credential_ref"])
            if raw:
                try:
                    token = json.loads(raw).get("access_token", "")
                except Exception:
                    print("Failed to parse Dropbox creds from store", file=sys.stderr)
        return DropboxProvider(token, config.get("remote_root", "/SaveSync"))
    elif kind == "google_drive":
        creds = config.get("credentials")
        if creds:
            return GoogleDriveProvider(creds, config.get("folder_id"))
        if "credential_ref" in config:
            from credential_store import get_credential_store
            store = get_credential_store()
            raw = store.get("savesync", config["credential_ref"])
            if raw:
                try:
                    creds = json.loads(raw).get("raw_credentials", {})
                    if creds:
                        return GoogleDriveProvider(creds, config.get("folder_id"))
                except Exception:
                    print("Failed to parse Google Drive creds from store", file=sys.stderr)
        raise ValueError("Google Drive requires 'credentials' in provider config. Use the Cloud Wizard to authenticate.")
    elif kind == "onedrive":
        token = config.get("token", "")
        if not token and "credential_ref" in config:
            from credential_store import get_credential_store
            store = get_credential_store()
            raw = store.get("savesync", config["credential_ref"])
            if raw:
                try:
                    token = json.loads(raw).get("access_token", "")
                except Exception:
                    print("Failed to parse OneDrive token from store", file=sys.stderr)
        return OneDriveProvider(token)
    raise ValueError(f"Unknown provider: {kind}")
