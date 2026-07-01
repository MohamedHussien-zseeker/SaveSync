# Contributing to SaveSync

SaveSync is a private-source project. This document is for internal development and for future contributors if the project opens.

---

## Setup

**Requirements:** Python 3.7+, Windows (primary) or Linux (development)

```bash
git clone <repo-url>
cd SaveSync
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
```

No dependencies to install. SaveSync uses Python standard library only.

Run the application:
```bash
python SaveSync.py
```

Run tests:
```bash
python -m pytest tests/ -v
```

Build Windows EXE (requires Docker on a Linux host):
```bash
# See SETUP.md for the full build pipeline
```

---

## Coding Principles

1. **Stdlib-only.** No external Python dependencies. If you need a library, implement it using stdlib or reconsider the approach.
2. **Thread safety.** The GUI thread must never block. Workers receive frozen `OperationContext` dataclasses — never mutable profile objects.
3. **No silent failures.** Every error must have a stable code (SS1000+), a human-readable message, and be logged.
4. **Restore is as important as backup.** Both paths must be tested with equal rigor.
5. **Test failure paths.** Every operation should have failure injection tests. Production code uses `_failure_policy` hooks that are inactive by default.

---

## Code Style

- Python 3.7+ compatible syntax
- No type annotations required (Python 3.7 compatibility)
- Descriptive variable and function names
- Comments for non-obvious thread-safety guarantees
- Logging over print statements

---

## Testing

Tests live in `tests/` and use pytest:

| File | Focus |
|------|-------|
| `test_savesync.py` | Core sync/restore, OAuth, config, CLI flags |
| `test_failures.py` | Failure injection (disk full, corrupt, network loss, etc.) |
| `test_concurrency_stress.py` | Thread safety, cancellation, race conditions |
| `test_upgrade.py` | Config migration from v1.x |
| `failure_policy.py` | Failure hook registry for test injection |

All 153 tests must pass before any merge:
```bash
python -m pytest tests/ -v --tb=short
```

---

## Pull Request Process

1. Ensure all tests pass.
2. Update `RELEASE_NOTES.md` if the change affects users.
3. Update `DECISIONS.md` if the change represents a new architectural decision.
4. No new features during v2.4.x beta — only P0 (data loss/crash) and P1 (broken workflow) fixes.

---

## Versioning

SaveSync follows semver-style versioning: `major.minor.patch[-pre]`.

- Pre-release tags (`-beta1`, `-rc1`) indicate unstable builds.
- Stable releases have no suffix.
- The v2.4.x branch is frozen for beta. Breaking changes wait for v2.5.
