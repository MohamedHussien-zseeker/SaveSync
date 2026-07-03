# SaveSync Logging & Observability System

## Purpose

The goal of this system is to capture everything that happens inside SaveSync during development and testing.

The logging system makes it possible to:

- Debug failures
- Replay user sessions
- Track AI decisions
- Monitor file synchronization
- Audit database changes
- Analyze performance
- Investigate crashes

---

## Architecture

```
User
 │
 ▼
SaveSync App
 │
 ├── Filesystem Logger (filesystem.jsonl)
 ├── Sync Logger (sync.jsonl)
 ├── API Logger (api.jsonl)
 ├── AI Logger (ai.jsonl)
 ├── Database Logger (database.jsonl)
 ├── Error Logger (errors.jsonl)
 ├── Metrics Logger (metrics.jsonl)
 ├── Session Logger (sessions.jsonl)
 └── Audit Logger (audit.jsonl)
 │
 ▼
logs/
```

---

## Directory Structure

```
SaveSync/
├── logs/
│   ├── filesystem.jsonl
│   ├── sync.jsonl
│   ├── api.jsonl
│   ├── ai.jsonl
│   ├── database.jsonl
│   ├── errors.jsonl
│   ├── metrics.jsonl
│   ├── sessions.jsonl
│   └── audit.jsonl
├── recordings/
├── screenshots/
└── app/
```

---

## Event Format

All logs use structured JSONL (one JSON object per line).

```json
{
  "timestamp": "2026-06-23T12:00:00.123456Z",
  "event_type": "file_created",
  "session_id": "sess_123",
  "user_id": "local_user",
  "data": {
    "path": "/docs/test.txt"
  }
}
```

---

## Session Tracking

Every user interaction belongs to a session. The session tracker logs start and end events.

Fields:
- `session_id` — unique hex ID per app launch
- `user_id` — local_user (default)
- `device` — platform identifier
- `started_at` / `ended_at` — UTC timestamps

Session replay: all events from a session can be retrieved and sorted by timestamp.

---

## Loggers

### Filesystem Logger

Tracks all file operations.

Events: `file_created`, `file_modified`, `file_deleted`, `file_renamed`, `folder_created`, `folder_deleted`

### Sync Logger

Tracks every synchronization event.

Events: `sync_started`, `sync_completed`, `sync_failed`, `file_uploaded`, `file_downloaded`, `file_conflict_detected`

### API Logger

Tracks all API requests and responses (for cloud provider calls).

Events: `api_request`, `api_response`

### AI Logger

Tracks AI activity including prompts, tool calls, and model responses.

Events: `ai_request`, `ai_response`, `tool_call`, `tool_result`

### Database Logger

Tracks all data modifications.

Events: `db_insert`, `db_update`, `db_delete`

### Error Logger

Captures all exceptions with full stack traces.

Events: `error`

Fields:
- `module` — source module name
- `error_type` — exception class name
- `message` — error description
- `stack_trace` — full Python traceback
- `request_id` — optional correlation ID

### Metrics Logger

Tracks application performance metrics.

Event: `metric`

Fields:
- `memory_mb` — memory usage
- `cpu_percent` — CPU usage
- `disk_usage_mb` — disk usage
- `sync_duration_ms` — sync operation duration
- `api_duration_ms` — API call duration
- `ai_latency_ms` — AI response latency

### Audit Logger

Records critical user actions.

Events: `user_login`, `user_logout`, `setting_changed`, `sync_configuration_changed`, `ai_configuration_changed`, `profile_switched`, `profile_created`, `profile_deleted`, `sync_started`, `sync_stopped`, `restore_requested`, `restore_started`, `restore_completed`, `manual_sync`, `watch_dir_added`, `watch_dir_removed`

---

## Log Retention

| Environment | Retention |
|-------------|-----------|
| Development | 30 days |
| Production  | 90 days |

Old log entries are automatically cleaned up once per day via a background timer.

---

## Session Replay

Every event is tagged with a `session_id`. To replay a session:

```python
from logging_system import get_logging_system

log = get_logging_system()
timeline = log.replay_session("sess_abc123")
for event in timeline:
    print(event["timestamp"], event["event_type"], event["data"])
```

---

## Integration Points

- `SaveSyncCore` — profile operations, error capture
- `SaveSyncDaemon` — sync lifecycle, file detection, restore operations
- `CloudProvider` subclasses — upload/download failures
- `SaveSync.py` GUI — profile switches, sync toggles, manual operations

---

## Future Improvements

- OpenTelemetry Integration
- Grafana Dashboard
- ClickHouse Analytics
- Real-time Monitoring
- AI Session Replay Viewer
- Distributed Tracing
- Alerting System
