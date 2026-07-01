#!/usr/bin/env python3
import json
import os
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any


def _logs_dir() -> Path:
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).parent.resolve()
    else:
        app_dir = Path(sys.argv[0]).parent.resolve()
    try:
        test = app_dir / ".writable_test"
        test.touch()
        test.unlink()
        return app_dir / "logs"
    except (OSError, PermissionError):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        log_dir = base / "SaveSync" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir


_RETENTION_DAYS = {
    "development": 30,
    "production": 90,
}
_CURRENT_ENV = "development"


def set_env(env: str):
    global _CURRENT_ENV
    _CURRENT_ENV = env


class LogEvent:
    def __init__(self, event_type: str, session_id: str, data: Optional[Dict] = None,
                 user_id: str = "local_user"):
        self.timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") + \
                         f"{datetime.utcnow().microsecond:06d}Z"
        self.event_type = event_type
        self.session_id = session_id
        self.user_id = user_id
        self.data = data or {}

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "data": self.data,
        }


class JsonLogger:
    def __init__(self, filename: str):
        self.path = _logs_dir() / filename
        _logs_dir().mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: LogEvent):
        with self._lock:
            try:
                with open(str(self.path), "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            except Exception:
                print("JsonLogger.write failed", file=sys.stderr)

    def read_all(self) -> List[Dict]:
        if not self.path.exists():
            return []
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").strip().split("\n")
                return [json.loads(l) for l in lines if l]
            except Exception:
                return []

    def count(self) -> int:
        if not self.path.exists():
            return 0
        try:
            return self.path.read_text(encoding="utf-8").count("\n")
        except Exception:
            return 0

    def cleanup(self, retention_days: Optional[int] = None):
        if retention_days is None:
            retention_days = _RETENTION_DAYS.get(_CURRENT_ENV, 30)
        cutoff = datetime.utcnow().timestamp() - retention_days * 86400
        events = self.read_all()
        kept = [e for e in events
                if self._event_time(e) > cutoff]
        if len(kept) < len(events):
            with self._lock:
                try:
                    self.path.write_text(
                        "\n".join(json.dumps(e, ensure_ascii=False) for e in kept),
                        encoding="utf-8"
                    )
                except Exception:
                    print("JsonLogger.cleanup failed", file=sys.stderr)

    @staticmethod
    def _event_time(event: Dict) -> float:
        try:
            ts = event.get("timestamp", "")
            return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except (ValueError, IndexError):
            return 0


class SessionTracker:
    def __init__(self):
        self.session_id = uuid.uuid4().hex[:12]
        self.user_id = "local_user"
        self.device = sys.platform
        self.platform = sys.platform
        self.started_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        self.ended_at: Optional[str] = None
        self._logger = JsonLogger("sessions.jsonl")
        self._lock = threading.Lock()

    def start(self):
        self._logger.write(LogEvent(
            event_type="session_started",
            session_id=self.session_id,
            data={
                "session_id": self.session_id,
                "user_id": self.user_id,
                "device": self.device,
                "platform": self.platform,
                "started_at": self.started_at,
            }
        ))

    def end(self):
        self.ended_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        self._logger.write(LogEvent(
            event_type="session_ended",
            session_id=self.session_id,
            data={
                "session_id": self.session_id,
                "ended_at": self.ended_at,
            }
        ))

    def replay(self) -> List[Dict]:
        all_events: List[Dict] = []
        for entry in self._logger.read_all():
            if entry.get("data", {}).get("session_id") == self.session_id:
                all_events.append(entry)
        all_events.sort(key=lambda e: e.get("timestamp", ""))
        return all_events


class FilesystemLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("filesystem.jsonl")

    def created(self, path: str, size: int = 0):
        self._logger.write(LogEvent(
            event_type="file_created", session_id=self._session.session_id,
            data={"path": path, "size": size}
        ))

    def modified(self, path: str, size: int = 0):
        self._logger.write(LogEvent(
            event_type="file_modified", session_id=self._session.session_id,
            data={"path": path, "size": size}
        ))

    def deleted(self, path: str):
        self._logger.write(LogEvent(
            event_type="file_deleted", session_id=self._session.session_id,
            data={"path": path}
        ))

    def renamed(self, src: str, dst: str):
        self._logger.write(LogEvent(
            event_type="file_renamed", session_id=self._session.session_id,
            data={"source": src, "destination": dst}
        ))

    def folder_created(self, path: str):
        self._logger.write(LogEvent(
            event_type="folder_created", session_id=self._session.session_id,
            data={"path": path}
        ))

    def folder_deleted(self, path: str):
        self._logger.write(LogEvent(
            event_type="folder_deleted", session_id=self._session.session_id,
            data={"path": path}
        ))


class SyncLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("sync.jsonl")

    def started(self, sync_id: str, folder: str,
                 provider: str = ""):
        self._logger.write(LogEvent(
            event_type="sync_started", session_id=self._session.session_id,
            data={"sync_id": sync_id, "folder": folder, "provider": provider}
        ))

    def completed(self, sync_id: str, files_count: int = 0,
                  duration_ms: float = 0, provider: str = ""):
        self._logger.write(LogEvent(
            event_type="sync_completed", session_id=self._session.session_id,
            data={
                "sync_id": sync_id, "files_count": files_count,
                "duration_ms": duration_ms, "provider": provider,
            }
        ))

    def failed(self, sync_id: str, error: str, error_code: str = "",
               provider: str = "", duration_ms: float = 0):
        self._logger.write(LogEvent(
            event_type="sync_failed", session_id=self._session.session_id,
            data={
                "sync_id": sync_id, "error": error,
                "error_code": error_code, "provider": provider,
                "duration_ms": duration_ms,
            }
        ))

    def file_uploaded(self, rel_path: str, size: int = 0):
        self._logger.write(LogEvent(
            event_type="file_uploaded", session_id=self._session.session_id,
            data={"path": rel_path, "size": size}
        ))

    def file_downloaded(self, rel_path: str, size: int = 0):
        self._logger.write(LogEvent(
            event_type="file_downloaded", session_id=self._session.session_id,
            data={"path": rel_path, "size": size}
        ))

    def file_conflict(self, rel_path: str):
        self._logger.write(LogEvent(
            event_type="file_conflict_detected", session_id=self._session.session_id,
            data={"path": rel_path}
        ))


class ApiLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("api.jsonl")

    def request(self, method: str, endpoint: str, body: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="api_request", session_id=self._session.session_id,
            data={"method": method, "endpoint": endpoint, "body": body}
        ))

    def response(self, status: int, duration_ms: float, endpoint: str = ""):
        self._logger.write(LogEvent(
            event_type="api_response", session_id=self._session.session_id,
            data={"status": status, "duration_ms": duration_ms, "endpoint": endpoint}
        ))


class AiLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("ai.jsonl")

    def request(self, prompt: str, system_prompt: str = "", context: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="ai_request", session_id=self._session.session_id,
            data={
                "prompt": prompt,
                "system_prompt": system_prompt,
                "context": context,
            }
        ))

    def response(self, response_text: str, tokens: int = 0, latency_ms: float = 0.0):
        self._logger.write(LogEvent(
            event_type="ai_response", session_id=self._session.session_id,
            data={
                "response": response_text,
                "tokens": tokens,
                "latency_ms": latency_ms,
            }
        ))

    def tool_call(self, tool: str, arguments: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="tool_call", session_id=self._session.session_id,
            data={"tool": tool, "arguments": arguments}
        ))

    def tool_result(self, tool: str, success: bool, result: Optional[Any] = None):
        self._logger.write(LogEvent(
            event_type="tool_result", session_id=self._session.session_id,
            data={"tool": tool, "success": success, "result": str(result) if result else None}
        ))


class DatabaseLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("database.jsonl")

    def insert(self, table: str, record_id: Any, values: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="db_insert", session_id=self._session.session_id,
            data={"table": table, "record_id": str(record_id), "values": values}
        ))

    def update(self, table: str, record_id: Any, before: Optional[Dict] = None,
               after: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="db_update", session_id=self._session.session_id,
            data={"table": table, "record_id": str(record_id),
                  "before": before, "after": after}
        ))

    def delete(self, table: str, record_id: Any, before: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type="db_delete", session_id=self._session.session_id,
            data={"table": table, "record_id": str(record_id), "before": before}
        ))


class ErrorLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("errors.jsonl")
        self._count = 0

    def capture(self, module: str, error: Exception, request_id: str = "",
                 error_code: str = "", operation: str = "",
                 provider: str = "", duration_ms: float = 0):
        self._count += 1
        tb = traceback.format_exc()
        self._logger.write(LogEvent(
            event_type="error", session_id=self._session.session_id,
            data={
                "module": module,
                "error_type": type(error).__name__,
                "error_code": error_code,
                "message": str(error),
                "stack_trace": tb,
                "request_id": request_id,
                "operation": operation,
                "provider": provider,
                "duration_ms": duration_ms,
            }
        ))

    def capture_message(self, module: str, error_type: str, message: str,
                        stack_trace: str = "", request_id: str = "",
                        error_code: str = "", operation: str = "",
                        provider: str = "", duration_ms: float = 0):
        self._count += 1
        self._logger.write(LogEvent(
            event_type="error", session_id=self._session.session_id,
            data={
                "module": module,
                "error_type": error_type,
                "error_code": error_code,
                "message": message,
                "stack_trace": stack_trace,
                "request_id": request_id,
                "operation": operation,
                "provider": provider,
                "duration_ms": duration_ms,
            }
        ))

    @property
    def error_count(self) -> int:
        return self._count


class MetricsLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("metrics.jsonl")

    def record(self, memory_mb: float = 0, cpu_percent: float = 0,
               disk_usage_mb: float = 0, sync_duration_ms: float = 0,
               api_duration_ms: float = 0, ai_latency_ms: float = 0,
               **extra):
        data = {
            "memory_mb": memory_mb,
            "cpu_percent": cpu_percent,
            "disk_usage_mb": disk_usage_mb,
            "sync_duration_ms": sync_duration_ms,
            "api_duration_ms": api_duration_ms,
            "ai_latency_ms": ai_latency_ms,
        }
        data.update(extra)
        self._logger.write(LogEvent(
            event_type="metric", session_id=self._session.session_id,
            data=data
        ))


class AuditLogger:
    def __init__(self, session: SessionTracker):
        self._session = session
        self._logger = JsonLogger("audit.jsonl")

    def login(self):
        self._logger.write(LogEvent(
            event_type="user_login", session_id=self._session.session_id,
            data={"action": "login"}
        ))

    def logout(self):
        self._logger.write(LogEvent(
            event_type="user_logout", session_id=self._session.session_id,
            data={"action": "logout"}
        ))

    def setting_changed(self, setting: str, old_value: Any, new_value: Any):
        self._logger.write(LogEvent(
            event_type="setting_changed", session_id=self._session.session_id,
            data={
                "setting": setting,
                "old_value": old_value,
                "new_value": new_value,
            }
        ))

    def sync_config_changed(self, config: str, old_value: Any, new_value: Any):
        self._logger.write(LogEvent(
            event_type="sync_configuration_changed", session_id=self._session.session_id,
            data={
                "config": config,
                "old_value": old_value,
                "new_value": new_value,
            }
        ))

    def ai_config_changed(self, config: str, old_value: Any, new_value: Any):
        self._logger.write(LogEvent(
            event_type="ai_configuration_changed", session_id=self._session.session_id,
            data={
                "config": config,
                "old_value": old_value,
                "new_value": new_value,
            }
        ))

    def action(self, action: str, details: Optional[Dict] = None):
        self._logger.write(LogEvent(
            event_type=action, session_id=self._session.session_id,
            data=details or {}
        ))


class LoggingSystem:
    def __init__(self, env: str = "development"):
        set_env(env)
        self.session = SessionTracker()
        self.fs = FilesystemLogger(self.session)
        self.sync = SyncLogger(self.session)
        self.api = ApiLogger(self.session)
        self.ai = AiLogger(self.session)
        self.db = DatabaseLogger(self.session)
        self.errors = ErrorLogger(self.session)
        self.metrics = MetricsLogger(self.session)
        self.audit = AuditLogger(self.session)
        self._cleanup_timer: Optional[threading.Timer] = None

    def start_session(self):
        self.session.start()
        self._schedule_cleanup()

    def end_session(self):
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        self.session.end()

    def _schedule_cleanup(self):
        self._cleanup_timer = threading.Timer(86400.0, self._do_cleanup)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _do_cleanup(self):
        for name in ["filesystem.jsonl", "api.jsonl", "ai.jsonl", "database.jsonl",
                      "errors.jsonl", "metrics.jsonl", "sessions.jsonl", "audit.jsonl",
                      "sync.jsonl"]:
            jl = JsonLogger(name)
            jl.cleanup()
        self._schedule_cleanup()

    def replay_session(self, session_id: str) -> List[Dict]:
        timeline: List[Dict] = []
        for name in ["filesystem.jsonl", "sync.jsonl", "api.jsonl", "ai.jsonl",
                      "database.jsonl", "errors.jsonl", "metrics.jsonl", "audit.jsonl"]:
            jl = JsonLogger(name)
            for entry in jl.read_all():
                if entry.get("session_id") == session_id:
                    timeline.append(entry)
        timeline.sort(key=lambda e: e.get("timestamp", ""))
        return timeline

    def get_all_log_paths(self) -> Dict[str, str]:
        base = str(_logs_dir())
        return {
            "filesystem": os.path.join(base, "filesystem.jsonl"),
            "sync": os.path.join(base, "sync.jsonl"),
            "api": os.path.join(base, "api.jsonl"),
            "ai": os.path.join(base, "ai.jsonl"),
            "database": os.path.join(base, "database.jsonl"),
            "errors": os.path.join(base, "errors.jsonl"),
            "metrics": os.path.join(base, "metrics.jsonl"),
            "sessions": os.path.join(base, "sessions.jsonl"),
            "audit": os.path.join(base, "audit.jsonl"),
        }


_logging_system: Optional[LoggingSystem] = None
_logging_lock = threading.Lock()


def log_error(module: str, error: Exception, error_code: str = "",
              operation: str = "", provider: str = "",
              duration_ms: float = 0):
    ls = get_logging_system()
    ls.errors.capture(
        module=module, error=error, error_code=error_code,
        operation=operation, provider=provider, duration_ms=duration_ms)


def get_logging_system(env: str = "development") -> LoggingSystem:
    global _logging_system
    if _logging_system is None:
        with _logging_lock:
            if _logging_system is None:
                _logging_system = LoggingSystem(env)
                _logging_system.start_session()
    return _logging_system


def shutdown():
    global _logging_system
    if _logging_system:
        _logging_system.end_session()
        _logging_system = None
