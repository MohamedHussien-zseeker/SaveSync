# SaveSync Beta Status

**Version:** v2.4.0-beta1
**Release date:** 2026-07-01
**Status:** Pre-release — not production ready

---

## What Works Well Today

- Local folder backup and restore (verified with SHA-256)
- Dropbox, Google Drive, and OneDrive integration (requires BYO credentials)
- Automatic polling — watches source folders for changes and syncs
- CLI flags (`--sync-now`, `--cancel-after`, `--close-after`)
- Operation cancellation — safe to cancel mid-transfer
- Structured error logging with stable error codes
- All 153 automated tests pass (Linux)

---

## What Has Been Tested

| Area | Status |
|------|--------|
| Local sync/restore | ✅ Manual + automated |
| Cloud provider adapters | ✅ Unit tests only |
| Failure injection (disk full, network loss, corrupt files, permission denied) | ✅ Automated |
| Operation cancellation | ✅ Automated |
| Upgrade path (v1.x → v2.x) | ✅ Automated |
| Stress (concurrent file changes) | ✅ Automated |
| Windows EXE smoke test | ✅ (--version, --self-test, PE verification) |
| Windows EXE full UI | ⏳ Tested via Wine (headless — --help crashes, Tkinter requires display) |
| Real cloud OAuth end-to-end | ⏳ Requires BYO credentials — not validated outside unit tests |

---

## Known Limitations

- **No automatic game detection.** You must manually select your save folders.
- **Cloud providers require BYO OAuth credentials.** You need a Dropbox/Google/Microsoft developer account to create your own app key and secret. This is documented in the setup guide.
- **`--help` crashes in headless environments** (Tkinter requires a display). Works on real Windows.
- **Restore is intentionally conservative.** Existing files are not overwritten unless the backup option is explicitly selected.
- **No auto-update mechanism.** You must download new versions manually.
- **No system tray mode** (planned).
- **Configuration is manual.** No import/export of profiles yet.
- **Windows validation is incomplete.** Full manual testing on Windows 10 and 11 with real cloud provider authentication has not been completed.

---

## What Testers Should Focus On

| Priority | Area | Why |
|----------|------|-----|
| P0 | Local sync and restore | Core functionality — any failure here is a release blocker |
| P0 | Safe cancellation | Does the application recover cleanly from cancellation? |
| P1 | Cloud provider OAuth flows | Can you connect Dropbox, Google Drive, and OneDrive? |
| P1 | Restore correctness | Are restored files identical to originals? |
| P2 | UI clarity | Is the progress display understandable? Are errors clear? |
| P2 | Polling reliability | Does SaveSync detect changes within a reasonable time? |

---

## How to Report Issues

1. Check the [known limitations](#known-limitations) above to avoid duplicate reports.
2. Check the error log at `~/.savesync/logs/error.log` and include relevant entries.
3. Include:
   - SaveSync version (run `SaveSync.exe --version`)
   - Windows version
   - Steps to reproduce
   - What you expected to happen
   - What actually happened
   - Error code (e.g., SS2001) if available

**Report to:** [beta@savesync.app — pending]

**Response target:** 48 hours for P0 (data loss/crash), 1 week for P1 (broken workflow), best effort for P2.

---

## Promotion Criteria to v2.4.0 Stable

All of these must be met before promoting the beta to stable:

- No unresolved P0 issues (data loss, crash, unrecoverable error)
- No unresolved P1 issues (broken workflow, incorrect behavior)
- Cloud OAuth end-to-end validated on real Windows for all three providers
- Full manual test pass on Windows 10 and 11
- Test feedback reviewed and categorized
- Known limitations documented and acknowledged
- At least 5 external testers have completed a sync and restore

---

## Changelog

See [RELEASE_NOTES.md](RELEASE_NOTES.md) for the full changelog.
