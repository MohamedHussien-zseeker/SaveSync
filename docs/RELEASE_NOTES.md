# SaveSync 2.0.0-rc.1 — Release Candidate

**Build date:** 2026-07-02
**Previous version:** 2.4.0-beta1 (2026-07-01)

**Build platform:** Linux x86_64 (PyInstaller 6.21.0)
**Binary SHA-256:** `54a24b90e99621cc6edafba7f880645ba600327d077cdd204782d9adcc28dd67`
**Binary size:** 13 MB
**Tests:** 192/192 passing (all workflows, all DPIs)

## Release Gate Status

| Gate | Status |
|------|--------|
| Workflow tests passing | ✅ 192 passing |
| Accessibility checklist | ✅ 38/38 items passing (Linux) |
| Packaging validation | ✅ Linux PyInstaller build validated |
| Critical defects | 0 |
| Known release blockers | Windows validation only (installer, code signing, High Contrast) |

## What's New Since v2.4.0-beta1

### Phase 1C — Component Cleanup
- Remaining UI polish and dead-code removal
- Consistent widget styling across all tabs

### Phase 1D — Workflow UI Testing
- **39 workflow tests** across 6 test files (profile CRUD, provider connection, sync/restore, dashboard, activity log, lifecycle)
- Test infrastructure: `app_factory.py`, `fake_filesystem.py`, `fake_provider.py`, `sample_profiles.py`
- UI action helpers: `select_tab`, `click_button`, `set_entry_text`, `select_tree_item`
- Assertion helpers: `assert_text_visible`, `assert_button_enabled`, `assert_button_disabled`
- All tests deterministic: no network, no real credentials, no `sleep()`

### Phase 1E — Accessibility Audit
- **38 items** across 6 passes: keyboard navigation, focus visibility, WCAG AA contrast, layout resilience, display scaling, OS integration
- 3 WCAG AA contrast failures fixed (empty text: 2.76→8.10, hint text: same, border: 1.74→2.37)
- DPI scaling validated at 96 / 144 / 192 DPI
- Keyboard: Escape on all dialogs, Return activation, visible focus indicators
- `--help` flag added

### Phase 1F — Packaging & Release Validation
- PyInstaller 6.21.0 single-file build (13 MB ELF)
- Minimal binary dependencies (libdl, libz, libpthread, libc)
- Optional cloud provider deps handled gracefully (delayed imports)
- `docs/RELEASE_CHECKLIST.md` — build, artifact, and runtime validation

## Build Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| Phase 0 | Architecture refactor | ✅ Complete |
| Phase 1A | CustomTkinter migration | ✅ Complete |
| Phase 1B | Premium UI redesign | ✅ Complete |
| Phase 1C | Component cleanup | ✅ Complete |
| Phase 1D | Workflow UI testing | ✅ Complete |
| Phase 1E | Accessibility audit | ✅ Complete |
| Phase 1F | Packaging & release validation | ✅ Complete (Linux) |
| v2.0.0 RC | Feature freeze, regression run, release | ✅ This build |

## Known Limitations (RC)

- **Windows packaging pending** — installer, code signing, SmartScreen reputation not validated on this platform
- **Windows High Contrast mode** — not tested (no Windows environment available)
- **Auto-update mechanism** — not yet implemented
- **Application icon** — no custom `.ico` bundled; uses default tkinter icon
- **Cloud OAuth** — requires BYO application credentials per provider (Google Drive, Dropbox, OneDrive)

## Build Dependencies

- Python 3.12 (stdlib only: tkinter, hashlib, json, threading, logging)
- PyInstaller 6.21.0
- No external Python packages required for core functionality
