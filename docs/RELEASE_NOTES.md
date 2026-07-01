# SaveSync 2.4.0-beta1 — Reliability & Resilience

**Build date:** 2026-07-01
**Previous version:** 2.3.2 (2026-06-27)

**Archived release:** `SaveSync-v2.4.0-beta1/`
**Build platform:** Docker cross-compile via `cdrx/pyinstaller-windows`
**PyInstaller:** 5.13.2 (upgraded from image default 3.6)
**EXE SHA-256:** `5cb03e2ff57d45de7eccde72e777a266515d8e2425c13462ff4f95a39c0b1054`
**EXE size:** 10,892,542 bytes (10.9 MB)
**Source archive SHA-256:** `facf8a13a3b8921b7bd113dbdde8b4b8a7897396d066c93548023410cb1a8e83`
**Tests:** 153/153 passing

## What's New

### Real-Time Progress UI (M4)
- Dedicated progress frame replaces status-bar widgets during sync/restore
- Indeterminate progress bar during scanning; determinate with per-file granularity during transfer
- Live speed display (EMA over rolling 5-second window)
- Bytes transferred / total with file-level tracking
- Dedicated Cancel button with safe teardown
- Generation-counter guards prevent stale callbacks from affecting new operations

### Background Thread Safety (M5)
- `OperationContext` frozen dataclass — worker threads never reference mutable `Profile` objects directly
- `_profiles_lock` guarding all profile/account list mutations
- `_running` boolean removed — `is_alive()` via `thread.is_alive()` eliminates TOCTOU race
- `on_close` rewritten — `worker.cancel()` → `worker._thread.join(timeout=5)` → abandon; prevents both hang and double-sync
- 100-cycle concurrency stress test (50 deterministic + 50 randomized scenarios)

### Failure Resilience (M6)
- `TransferManager` with 8 lifecycle hooks for testable failure injection (`_failure_policy` param, production-inactive by default)
- `sync_all_now` error tracking — errors counter propagated through `done_callback`; operations finish with explicit success/failure
- Thread-safe `OperationState` with phase machine (Idle → Scanning → Uploading/Downloading → Verifying → Completed/Cancelled/Failed)
- Immutable `FrozenSnapshot` dataclass prevents accidental widget writes from background threads
- 26 failure-injection tests covering: read-only dest, cancel during sync/restore, unicode paths, long paths, fail-then-retry, cleanup, thread leak detection

### Streaming Large-File Transfers (M3)
- Chunked I/O with 8 MiB buffers across all four providers
- **Local:** chunked copy with live progress callbacks
- **Dropbox:** session uploads (start/append/finish)
- **Google Drive:** `MediaFileUpload(chunksize=8MiB)` + `next_chunk()` loop
- **OneDrive:** upload session with `Content-Range` headers
- SHA-256 verification after transfer
- 5 GB soak test: 640 chunks, peak RSS 35.8 MB, zero leaks, clean cancel at 10% and 90%

### Error Handling & Diagnostics (M2)
- Structured error hierarchy: `SaveSyncError` → `AuthError`, `ProviderError`, `SyncError`, `VerificationError`, `ConflictError`, `ConfigError`, `OperationCancelled` (codes SS1000–SS7000)
- All 16 bare `except Exception: pass` sites replaced with structured logging
- `SyncLogger` / `ErrorLogger` with JSON fields: `error_code`, `operation`, `provider`, `duration_ms`
- Background thread exceptions routed via `done_callback` → `root.after(0)` plus `log_error()`
- Op-ID logging — each `OperationContext` carries UUID hex attached to audit actions

### Off-Main-Thread Sync/Restore (M1)
- `SyncWorker` class runs all sync/restore/OAuth operations in background threads
- `done_callback` + `root.after(0)` for safe UI updates
- Pre-restore backup and SHA-256 verification for restore safety
- Thread locks for credential store access

## Files Modified
- `SaveSync.py` — Progress frame, `_poll_state(gen)`, `_handle_done()`, generation counter
- `core.py` — `OperationContext`, `_profiles_lock`, `SyncWorker` rewrite, error tracking
- `state.py` — [new] `OperationState` + `FrozenSnapshot`
- `transfer.py` — `TransferManager` with chunked streaming, retry, `_failure_policy` hooks
- `providers.py` — `progress_callback` on all four adapters
- `cloud.py` — Legacy provider progress callbacks
- `exceptions.py` — [new] Error hierarchy SS1000–SS7000
- `logging_system.py` — Structured JSON logging with `log_error()`

## Tests
- 153 tests passing (up from 67)
- New test files: `tests/test_failures.py` (26 tests), `tests/test_upgrade.py` (5), `tests/test_concurrency_stress.py` (2), `tests/failure_policy.py`
- New test classes: `TestOperationState`, `TestProviderProgressCallback`, `TestSyncWorkerStateIntegration`, `TestFailurePolicy*`, `TestFailureIntegration*`, `TestUpgrade*`

## Windows Validation (2026-06-30)
- Verified the release executable on Windows with SHA-256 `e0422e35fd5a47f6a15f19c9957cbdd3862206e818e81a029a326b53adbabaa4`
- `--version` and `--self-test` completed successfully
- GUI launched and rendered version `v2.4.0-beta1`
- Local-folder sync passed with nested paths, Unicode filenames, and a 100 MiB file
- Source and backup SHA-256 hashes matched for the Unicode and 100 MiB fixtures
- Cloud OAuth, restore, cancellation, and shutdown-during-transfer validation are deferred to a future phase

## Known Limitations (Beta)
- Windows validation is partial; Google Drive, Dropbox, and OneDrive require dedicated BYO OAuth application credentials
- Restore, cancellation, and shutdown-during-transfer remain pending manual Windows validation
- PyInstaller 5.13.2 used for final build (upgraded from image default 3.6 via `requirements-windows.txt`)
- `ResourceWarning: unclosed file` in two failure-injection test fixtures (test-only, not production)
- M5 concurrency stress test requires 5+ minutes for randomized cycle scenarios

## Build Dependencies
- Python 3.7+ (stdlib only: tkinter, hashlib, json, threading, logging)
- Windows build: `cdrx/pyinstaller-windows` (Docker/wine cross-compile)
- No external Python packages required
