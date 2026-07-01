import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


GB = 1024 ** 3


@dataclass(frozen=True)
class FrozenSnapshot:
    phase: str
    files_completed: int
    files_total: int
    bytes_transferred: int
    bytes_total: int
    current_file: str
    provider: str
    profile: str
    duration_ms: float
    speed_bps: float
    eta_seconds: float

    @property
    def is_terminal(self) -> bool:
        return self.phase in ("Completed", "Cancelled", "Failed")

    @property
    def is_active(self) -> bool:
        return self.phase in (
            "Preparing", "Scanning", "Uploading",
            "Downloading", "Verifying", "Finishing",
        )


class OperationState:
    def __init__(self):
        self._lock = threading.Lock()
        self._phase: str = "Idle"
        self._files_completed: int = 0
        self._files_total: int = 0
        self._bytes_transferred: int = 0
        self._bytes_total: int = 0
        self._current_file: str = ""
        self._provider: str = ""
        self._profile: str = ""
        self._started_at: float = 0.0
        self._ema_speed: float = 0.0
        self._last_update: float = 0.0
        self._last_bytes: int = 0

    def start(self, phase: str, provider: str, profile: str,
              files_total: int, bytes_total: int):
        with self._lock:
            self._phase = phase
            self._provider = provider
            self._profile = profile
            self._files_total = files_total
            self._bytes_total = bytes_total
            self._files_completed = 0
            self._bytes_transferred = 0
            self._current_file = ""
            self._started_at = time.time()
            self._last_update = self._started_at
            self._last_bytes = 0
            self._ema_speed = 0.0

    def set_phase(self, phase: str):
        with self._lock:
            self._phase = phase

    def set_current_file(self, filename: str):
        with self._lock:
            self._current_file = filename

    def incr_files(self):
        with self._lock:
            self._files_completed += 1

    def update_bytes(self, bytes_done: int, bytes_total: int):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            delta_bytes = bytes_done - self._last_bytes
            self._bytes_transferred = bytes_done
            self._bytes_total = bytes_total
            if elapsed > 0 and delta_bytes > 0:
                instant = delta_bytes / elapsed
                if self._ema_speed == 0:
                    self._ema_speed = instant
                else:
                    alpha = min(1.0, elapsed / 3.0)
                    self._ema_speed = (1 - alpha) * self._ema_speed + alpha * instant
            self._last_update = now
            self._last_bytes = bytes_done

    def cancel(self):
        with self._lock:
            self._phase = "Cancelled"

    def finish(self, success: bool = True):
        with self._lock:
            self._phase = "Completed" if success else "Failed"

    def snapshot(self) -> FrozenSnapshot:
        with self._lock:
            now = time.time()
            dur = (now - self._started_at) * 1000 if self._started_at > 0 else 0.0
            speed = self._ema_speed
            eta = 0.0
            if speed > 0 and self._bytes_total > self._bytes_transferred:
                remaining = self._bytes_total - self._bytes_transferred
                eta = remaining / speed
            return FrozenSnapshot(
                phase=self._phase,
                files_completed=self._files_completed,
                files_total=self._files_total,
                bytes_transferred=self._bytes_transferred,
                bytes_total=self._bytes_total,
                current_file=self._current_file,
                provider=self._provider,
                profile=self._profile,
                duration_ms=dur,
                speed_bps=speed,
                eta_seconds=eta,
            )
