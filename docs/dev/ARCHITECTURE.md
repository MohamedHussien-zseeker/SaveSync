# SaveSync Architecture

**How SaveSync works.**

---

## Overall Architecture

SaveSync is a single-process desktop application with two threads: a **GUI thread** (Tkinter event loop) and a **worker thread**. The GUI handles user input and display; the worker executes all file operations, uploads, and verification. Communication is one-way: the worker reports completion through a callback, which the GUI dispatches via `root.after(0)`.

The application uses no external dependencies beyond Python 3.7+ standard library.

---

## Data Flow

```
File Change Detected
        │
        ▼
  ┌─────────────┐
  │ Polling     │  (every N seconds, scans watched folders)
  │ Watcher     │
  └──────┬──────┘
         │ changed files
         ▼
  ┌─────────────┐
  │ Sync Queue  │  (pending operations, deduplicated)
  └──────┬──────┘
         │ dequeue next
         ▼
  ┌─────────────┐
  │ Worker      │  (background thread)
  │ Thread      │
  └──────┬──────┘
         │ copy/upload
         ▼
  ┌─────────────┐
  │ Provider    │  (Local, Dropbox, Google Drive, OneDrive)
  │ Adapter     │
  └──────┬──────┘
         │ written file
         ▼
  ┌─────────────┐
  │ Verification│  (SHA-256 checksum comparison)
  └──────┬──────┘
         │ result
         ▼
  ┌─────────────┐
  │ Logging +   │  (structured JSONL, UI progress update)
  │ UI Update   │
  └─────────────┘
```

---

## Major Components

### SaveSyncCore

Manages profiles, configuration, and account credentials. Owns the profile list and coordinates sync/restore operations. Thread-safe via a dedicated lock (`_profiles_lock`). Frozen snapshots are produced for safe UI reads without holding the lock.

### SaveSyncDaemon

Background polling loop that watches configured source folders for changes. Runs in the worker thread. Detects new, modified, and deleted files by comparing directory state against a stored snapshot. Enqueues detected changes into the sync queue.

### SyncWorker

Executes a single sync or restore operation. Receives an `OperationContext` — a frozen dataclass containing the source, destination, provider, and mode. Reports progress and completion through a callback. The GUI never reads mutable worker state directly.

### TransferManager

Handles actual file I/O: reading source files in chunks, writing to destination, computing SHA-256 hashes during transfer. Supports resumable uploads for cloud providers. Ensures destination files are either fully written or unchanged on failure.

### ProviderAdapter (ABC)

Abstract base class for all storage backends. Defines `upload`, `download`, `delete`, `list_files`, `verify`. Four implementations:

| Provider | Auth | Notes |
|----------|------|-------|
| Local | None | Direct filesystem operations |
| Dropbox | OAuth 2.0 | PKCE flow, localhost callback |
| Google Drive | OAuth 2.0 | PKCE flow, localhost callback |
| OneDrive | OAuth 2.0 | PKCE flow, localhost callback |

---

## Threading Model

```
GUI Thread                     Worker Thread
(Event Loop)                   (Background)
    │                              │
    │  ┌──────────────────┐        │
    │  │ User input       │        │
    │  │ Progress display │        │
    │  │ Status updates   │        │
    │  └──────────────────┘        │
    │                              │
    │  root.after(200ms)           │
    │  polls frozen state          │
    │                              │
    │  ─ ─ ─ SyncRequest ─ ─ ─ ─ ▶│
    │                              │  ┌──────────────────┐
    │                              │  │ File copy        │
    │                              │  │ Upload           │
    │                              │  │ Verification     │
    │                              │  │ Result callback  │
    │                              │  └──────────────────┘
    │  ◀ ─ ─ done_callback ─ ─ ─ ─│
    │                              │
    │  ┌──────────────────┐        │
    │  │ _handle_done()   │        │
    │  │ (root.after)     │        │
    │  └──────────────────┘        │
    │                              │
```

Key rules:

- **Never update widgets from the worker thread.** All UI updates go through `_poll_state()` (periodic timer) or `_handle_done()` (completion callback).
- **`OperationContext` is frozen.** The worker receives a snapshot of profile state; it cannot read mutable fields that might change during operation.
- **Generation counter.** A counter increments with each new operation. Stale results from cancelled operations are discarded.
- **Cancellation.** Setting a flag tells the worker to stop after the current file. The worker checks the flag between chunks.

---

## Provider Abstraction

Every storage backend implements the same interface:

```python
class ProviderAdapter(ABC):
    @abstractmethod
    def upload(self, source_path, dest_path, progress_callback)
    @abstractmethod
    def download(self, source_path, dest_path, progress_callback)
    @abstractmethod
    def delete(self, path)
    @abstractmethod
    def list_files(self, prefix)
    @abstractmethod
    def verify(self, path, expected_hash)
```

Providers are discovered through a registry and selected by profile configuration. Adding a new provider means implementing this interface and registering it — no other code changes required.

---

## Restore Pipeline

```
Restore Request
      │
      ▼
  ┌────────────────┐
  │ Pre-restore    │  (backup existing files before overwriting)
  │ Backup         │
  └──────┬─────────┘
         │
         ▼
  ┌────────────────┐
  │ Download /     │  (copy files from destination back to source)
  │ Copy           │
  └──────┬─────────┘
         │
         ▼
  ┌────────────────┐
  │ SHA-256        │  (verify each restored file matches)
  │ Verification   │
  └──────┬─────────┘
         │
         ▼
  ┌────────────────┐
  │ Non-destructive│  (existing files are not overwritten unless
  │                │   the backup option is explicitly selected)
  └────────────────┘
```

Restore is tested with the same rigor as sync. The pre-restore backup means an interrupted restore leaves the original files intact.

---

## Configuration Storage

Profiles, accounts, and settings are stored in JSON files under `~/.savesync/`:

- `profiles.json` — profile definitions (source folder, destination, provider, schedule)
- `accounts.json` — encrypted provider credentials (tokens, not secrets)
- `settings.json` — application preferences
- `state/` — polling snapshots for change detection

OAuth tokens are stored via the OS credential API (DPAPI on Windows) and are never written to logs or config files in plaintext.

---

## Logging & Error Handling

SaveSync uses structured JSONL logging with separate log files per domain:

| Log | Content | Retention |
|-----|---------|-----------|
| `sync.log` | File operations, transfers, verification results | 30 days |
| `audit.log` | Profile changes, account connections | 90 days |
| `filesystem.log` | Polling details, file change events | 7 days |
| `error.log` | All errors with codes, context, stack traces | 90 days |
| `session.log` | Session start/stop, operation boundaries | 30 days |

Each session generates a unique session ID that links across all log files, enabling full request tracing for any operation.

### Error Hierarchy

Errors use a structured hierarchy with stable codes:

| Range | Domain |
|-------|--------|
| SS1000–SS1999 | General / configuration |
| SS2000–SS2999 | Filesystem |
| SS3000–SS3999 | Network / provider |
| SS4000–SS4999 | Authentication |
| SS5000–SS5999 | Verification |
| SS6000–SS6999 | Internal |

Every error has: a code, a human-readable message, the operation context, elapsed time, and the provider involved. Silent failures are never acceptable.

---

## Security Model

- **No telemetry.** SaveSync never phones home. No analytics, no crash reporting, no usage tracking.
- **Local-first.** All features work offline. Cloud connectivity is optional.
- **Credentials on device.** OAuth tokens are stored using OS-level credential APIs. They are never logged, never transmitted except to the provider's API, and never readable in config files.
- **BYO credentials.** Users provide their own OAuth app keys for cloud providers. SaveSync does not operate a central OAuth server.
- **Verified transfers.** Every file operation includes SHA-256 verification on both sync and restore paths.
- **No silent failures.** Every error is surfaced in the UI, logged with context, and assigned a stable error code.

---

## Design Trade-offs

| Decision | Rationale | Cost |
|----------|-----------|------|
| Stdlib only | Eliminates bundling failures, works with any Python 3.7+ | No rich third-party libraries |
| Polling (not filesystem hooks) | No native deps, works identically on all platforms | Higher latency, small CPU cost |
| Tkinter (not Qt/Wx/Web) | Ships with Python, no bundling hassle | Limited UI capabilities |
| Single worker thread | Simple concurrency model, no deadlocks | One operation at a time |
| BYO OAuth credentials | No server infrastructure to maintain | User must set up app credentials |
| Windows-first | Target market is PC gamers | Mac/Linux support is secondary |
| JSONL logging | Machine-parseable, append-only, no rotation complexity | Larger disk footprint |
| Frozen OperationContext | No thread safety bugs from mutable state | Slightly more memory per operation |
