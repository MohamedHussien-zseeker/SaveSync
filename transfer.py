import hashlib
import os
import threading
import time
from typing import Callable, Optional


CHUNK_SIZE = 8 * 1024 * 1024
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0


class TransferManager:
    def __init__(self, progress_callback: Optional[Callable] = None,
                 cancel_event: Optional[threading.Event] = None,
                 _failure_policy=None):
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self._failure_policy = _failure_policy
        self.bytes_read = 0
        self.total_bytes = 0
        self._current_file: str = ""

    def set_current_file(self, filename: str):
        self._current_file = filename

    def read_chunks(self, src_path: str):
        self.bytes_read = 0
        if self._failure_policy:
            self._failure_policy.before_open()
        try:
            self.total_bytes = os.path.getsize(src_path)
        except OSError:
            self.total_bytes = 0
        f = open(src_path, "rb")
        if self._failure_policy:
            self._failure_policy.after_open()
        try:
            chunk_idx = 0
            while True:
                if self._failure_policy:
                    self._failure_policy.before_transfer_chunk(chunk_idx)
                if self.cancel_event and self.cancel_event.is_set():
                    return
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                self.bytes_read += len(chunk)
                if self.progress_callback:
                    self.progress_callback(self.bytes_read, self.total_bytes)
                if self._failure_policy:
                    self._failure_policy.after_transfer_chunk(chunk_idx)
                chunk_idx += 1
                yield chunk
        finally:
            if self._failure_policy:
                self._failure_policy.before_close()
            f.close()

    def checksum(self, file_path: str) -> str:
        if self._failure_policy:
            self._failure_policy.before_verify()
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def write_stream(self, dest_path: str, chunk_iter):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        self.bytes_read = 0
        h = hashlib.sha256()
        f = open(dest_path, "wb")
        try:
            for chunk in chunk_iter:
                if self._failure_policy:
                    self._failure_policy.before_transfer_chunk(0)
                if self.cancel_event and self.cancel_event.is_set():
                    return False
                f.write(chunk)
                h.update(chunk)
                self.bytes_read += len(chunk)
                if self.progress_callback:
                    self.progress_callback(self.bytes_read, self.total_bytes)
        finally:
            if self._failure_policy:
                self._failure_policy.before_close()
            f.close()
        if self._failure_policy:
            self._failure_policy.before_commit()
        return h.hexdigest()

    @staticmethod
    def retry(fn, retries: int = MAX_RETRIES, backoff: float = RETRY_BACKOFF,
              _failure_policy=None):
        last_exc = None
        for attempt in range(retries):
            if _failure_policy:
                _failure_policy.before_retry(attempt)
            try:
                return fn()
            except Exception as e:
                last_exc = e
                if attempt < retries - 1:
                    time.sleep(backoff * (2 ** attempt))
        raise last_exc
