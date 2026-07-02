# Test Strategy — SaveSync

## Test Pyramid

```
      ╱╲
     ╱  ╲
    ╱ WK ╲       Workflow tests — full user scenarios
   ╱──────╲
  ╱  SMK   ╲     Smoke tests — GUI boots, tabs render, CLI flags
 ╱──────────╲
╱  SELF-TST  ╲   Self‑tests — headless import/init/version validation
╱──────────────╲
```

| Level | What | How |
|-------|------|-----|
| **Self-test** | `--self-test` flag imports and initializes every module without opening the GUI | `SaveSync.py:15` — runs headless, no tkinter display required |
| **Smoke** | App launches under Xvfb, window exists, status bar renders, all 5 notebook tabs present | `pytest + xvfb` — verifies boot integrity |
| **Workflow** | Full user scenarios: profile CRUD, provider connect, sync/restore, tab navigation, keyboard flow | Simulated events on real widgets via `update()` |

## Phase 1D Scope

### In-Scope Workflows

| Priority | Workflow | Rationale |
|----------|----------|-----------|
| P0 | Profile CRUD (create, select, rename, delete) | Core functionality everything else depends on |
| P0 | Connect/disconnect provider (local folder) | Exercises dialogs, provider registry, state updates |
| P0 | Sync Now / Cancel / Restore | Highest-risk threaded operations |
| P1 | Dashboard refresh — stats, status bar updates | Verifies UI state propagation |
| P1 | Activity log — messages render, color tags, clear | Confirms log handler + UI integration |
| P1 | Keyboard navigation & dialog flow | Baseline before Phase 1E accessibility |

### Out-of-Scope

- Visual regression / screenshot comparison
- Backend unit tests (153 existing in `test_savesync.py`)
- Cloud provider OAuth flows (require real credentials / network)
- Performance or load testing (covered by test_concurrency_stress.py)
- Cross-platform testing (Windows-first GUI)

## Test Suite Architecture

```
tests/
├── workflows/
│   ├── test_profile_crud.py
│   ├── test_provider_connection.py
│   ├── test_sync_restore.py
│   ├── test_dashboard.py
│   └── test_keyboard_navigation.py
├── fixtures/
│   ├── app_factory.py          # Build and tear down test app instance
│   ├── fake_provider.py        # Deterministic mock provider
│   ├── fake_filesystem.py      # In-memory file operations
│   └── sample_profiles.py      # Pre-built profile data
└── helpers/
    ├── ui_actions.py            # Reusable UI interaction wrappers
    └── assertions.py            # Custom assertion helpers
```

### Principles

- Prefer **stable selectors** (named widget attributes or component IDs) over widget hierarchy or visual position.
- **Mock cloud providers and filesystem** so tests are deterministic and fast.
- Test **observable behavior** (button enabled/disabled, status text, dialog open/close), not implementation internals.
- Reserve a small number of **end-to-end smoke tests** for real threading and lifecycle.

## Test Environment

| Component | Configuration |
|-----------|---------------|
| Display | Xvfb virtual framebuffer (`xvfb-run` or manual `$DISPLAY`) |
| Framework | pytest (no special plugin required) |
| Fixtures | `tmp_path` for sandboxed config, `monkeypatch` for config dirs |
| Accounts | Local provider only — no cloud credentials needed |
| Isolation | Each test creates its own temp config dir and app instance |

### CI Commands

```bash
# Full suite
xvfb-run pytest tests/ -v

# Workflow tests only
xvfb-run pytest tests/workflows/ -v

# Smoke test (headless boot)
python SaveSync.py --self-test
xvfb-run python -c "from SaveSync import main; main()"
```

## Pass / Fail Criteria

| Severity | Criteria | Action |
|----------|----------|--------|
| **Release blocker** | App crash on launch, profile data loss, sync corruption, broken core workflow | Must fix before v2.0.0 RC |
| **Non-blocking** | Minor UI alignment, color mismatch, console warning, missing tooltip | Fix post-release or next patch |

## Phase 1D Exit Criteria

- All P0 workflows passing on every commit.
- P1 workflows passing in CI.
- No test depends on network access or real cloud credentials.
- No test uses arbitrary `sleep()` — prefer waiting on application state or synchronization primitives.
- Full suite completes under 2 minutes to encourage frequent execution.
