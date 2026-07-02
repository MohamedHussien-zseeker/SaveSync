"""Deterministic fake provider for workflow tests.

Replaces real provider implementations with in-memory versions
so tests are fast, deterministic, and require no network or
cloud credentials.
"""
import hashlib
import os
from pathlib import Path
from typing import Optional


class FakeProvider:
    name = "FakeProvider"

    def __init__(self, root: str = ""):
        self._files: dict[str, bytes] = {}
        self._root = root
        self.upload_count = 0
        self.download_count = 0
        self.list_count = 0

    def upload(self, src_path: str, rel_path: str, **kwargs) -> bool:
        try:
            with open(src_path, "rb") as f:
                self._files[rel_path] = f.read()
            self.upload_count += 1
            return True
        except FileNotFoundError:
            return False

    def download(self, dest_path: str, rel_path: str, **kwargs) -> bool:
        if rel_path not in self._files:
            return False
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(self._files[rel_path])
        self.download_count += 1
        return True

    def list_files(self) -> list[str]:
        self.list_count += 1
        return list(self._files.keys())

    def test(self) -> str:
        return "OK (fake)"

    def delete(self, rel_path: str) -> bool:
        return self._files.pop(rel_path, None) is not None

    def clear(self):
        self._files.clear()
        self.upload_count = 0
        self.download_count = 0
        self.list_count = 0

    @property
    def file_count(self) -> int:
        return len(self._files)
