"""In-memory filesystem for deterministic workflow tests.

Simulates file create, write, read, delete, and metadata
operations without touching the real disk (except tmp_path
backed directories).
"""
import os
import time
from pathlib import Path
from typing import Optional


class FakeFilesystem:
    """In-memory file system backed by a tmp_path for scaffolding.

    Provides helper methods to create test file structures quickly.
    The actual file operations use real disk (tmp_path) so that
    SaveSync's os.path and open() calls work transparently.
    """

    def __init__(self, root: Path):
        self.root = root

    def create_file(self, rel_path: str, content: bytes | str = b"save data") -> Path:
        full = self.root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode()
        full.write_bytes(content)
        return full

    def create_files(self, count: int, prefix: str = "save", ext: str = ".sav") -> list[Path]:
        paths = []
        for i in range(count):
            p = self.create_file(f"{prefix}_{i}{ext}", f"data_{i}".encode())
            paths.append(p)
        return paths

    def read_file(self, rel_path: str) -> Optional[bytes]:
        full = self.root / rel_path
        if full.exists():
            return full.read_bytes()
        return None

    def file_exists(self, rel_path: str) -> bool:
        return (self.root / rel_path).exists()

    def file_size(self, rel_path: str) -> int:
        full = self.root / rel_path
        return full.stat().st_size if full.exists() else 0

    def delete_file(self, rel_path: str) -> bool:
        full = self.root / rel_path
        if full.exists():
            full.unlink()
            return True
        return False

    def list_files(self, subdir: str = "") -> list[str]:
        base = self.root / subdir if subdir else self.root
        if not base.exists():
            return []
        return [str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file()]

    def modify_file(self, rel_path: str, content: Optional[bytes] = None) -> bool:
        full = self.root / rel_path
        if not full.exists():
            return False
        if content is not None:
            full.write_bytes(content)
        else:
            full.write_bytes(full.read_bytes() + b"modified")
        return True
