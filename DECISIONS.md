# Decision Log

This document records the key architectural and strategic decisions that have shaped SaveSync. Each entry explains the context, alternatives considered, rationale, and consequences of a decision.

New entries follow this template:

- **Decision:** What was decided.
- **Date:** When the decision was made.
- **Status:** Active / Superseded / Reverted.
- **Context:** Why this decision was needed.
- **Alternatives:** What else was considered.
- **Rationale:** Why this option was chosen.
- **Consequences:** What this decision means going forward.

---

## Decision 1: Standard Library–Only Architecture

- **Date:** 2026-06-22
- **Status:** Active
- **Context:** The project originally used third-party dependencies (watchdog, requests, etc.). PyInstaller builds frequently broke due to incompatible or missing bundled dependencies. Each dependency update risked breaking the Windows build.
- **Alternatives:** Continue using third-party libraries with pinned versions; adopt Nuitka instead of PyInstaller; vendor dependencies.
- **Rationale:** Eliminating external dependencies removes the primary source of build failures and portability issues. Python 3.7+ stdlib provides everything needed: `http.server` for OAuth callbacks, `threading` for background work, `hashlib` for SHA-256, `json` for config, `tkinter` for the UI, `urllib` for HTTPS requests. The cost is acceptable given the project's scope.
- **Consequences:** No `requests` library means manual HTTP handling. No `watchdog` means polling-based file detection. No `keyring` means platform-specific credential API calls. All are manageable within stdlib. Builds are now reliable and portable.

---

## Decision 2: Tkinter for the GUI

- **Date:** 2026-06-22
- **Status:** Active
- **Context:** A GUI framework was needed for the desktop interface. The application required standard window management, buttons, list boxes, and progress bars.
- **Alternatives:** PyQt/PySide, wxPython, Electron, web-based UI.
- **Rationale:** Tkinter ships with Python stdlib. No additional dependency to bundle. Cross-platform. Sufficient for the application's UI needs. Other frameworks would require bundling (PyInstaller issues), increase executable size, and introduce platform-specific problems.
- **Consequences:** Limited widget set. No native-looking widgets without ttk theming. No hardware-accelerated rendering. No built-in async event loop — all background work must use threading with `root.after()` callbacks.

---

## Decision 3: Polling Instead of Filesystem Event Hooks

- **Date:** 2026-06-22
- **Status:** Active
- **Context:** The application needs to detect file changes in watched folders to trigger backups.
- **Alternatives:** Watchdog (Python library wrapping ReadDirectoryChangesW, inotify, FSEvents), manual Win32 API calls, manual Linux inotify calls.
- **Rationale:** Filesystem event libraries are platform-specific and require C extensions or native code — complicating PyInstaller builds. Polling uses only stdlib, works identically on all platforms, and has predictable behavior. The latency of polling (a few seconds) is acceptable for game save backups.
- **Consequences:** Slightly higher CPU usage during polling intervals. Change detection is not instantaneous. Polling interval must be tuned to balance responsiveness and resource usage.

---

## Decision 4: Local-First Architecture

- **Date:** 2026-06-22
- **Status:** Active
- **Context:** The application needed a core operating model. Early design considered whether to require cloud connectivity.
- **Alternatives:** Cloud-first (require account, make cloud primary); hybrid (sync to local, then to cloud as enhancement).
- **Rationale:** Game saves are personal files stored on the user's machine. Backing them up should not depend on internet connectivity, cloud provider availability, or account creation. Local-first ensures the application works offline and remains useful without any third-party service.
- **Consequences:** Cloud providers are optional add-ons, not requirements. All core features (sync, restore, scheduling, verification) work with local destinations. Provider abstraction naturally supports both local and remote storage.

---

## Decision 5: BYO OAuth Credentials

- **Date:** 2026-06-27
- **Status:** Active
- **Context:** Cloud provider integration requires OAuth app credentials (client ID, client secret) for authentication.
- **Alternatives:** Operate a central OAuth server with shared credentials; hardcode credentials in the application; use PKCE flow without client secret.
- **Rationale:** Operating a central OAuth server creates infrastructure costs, a single point of failure, and a security liability. Hardcoded credentials would be extracted from the binary and abused, risking provider API revocation. BYO credentials means zero server infrastructure, no shared secrets, and each user controls their own API access.
- **Consequences:** Users must create their own OAuth app credentials for each cloud provider. This adds setup friction that must be documented clearly. The application cannot obtain credentials automatically on first launch.

---

## Decision 6: Windows-First Support

- **Date:** 2026-06-22
- **Status:** Active
- **Context:** The target market for game save protection is overwhelmingly Windows PC gamers.
- **Alternatives:** Cross-platform from day one; macOS-first; Linux-first.
- **Rationale:** PC gaming occurs primarily on Windows. A cross-platform approach would multiply testing, platform-specific bug fixes, and release management. Focusing on Windows first allows a polished experience for the majority of users.
- **Consequences:** macOS and Linux support will lag. Some features (system tray, credential storage) use Windows-specific APIs. Future cross-platform work will require abstraction layers for these platform dependencies.

---

## Decision 7: Feature Freeze Before Commercialization

- **Date:** 2026-06-30
- **Status:** Active
- **Context:** The project reached a stable feature set sufficient for initial release. Before offering paid options, the application needed to prove reliability.
- **Alternatives:** Continue adding features indefinitely; commercialize immediately; skip beta.
- **Rationale:** Freezing features allows focus on bug fixes, reliability testing, and user feedback. Commercializing an unstable product would damage trust. The freeze covers the v2.4.x branch and will lift after stable release.
- **Consequences:** No new features during beta. Only P0/P1 bug fixes are accepted. This discipline ensures the stable release is reliable rather than feature-rich.

---

## Decision 8: Private Source with Permanent Free Edition

- **Date:** 2026-07-01
- **Status:** Active
- **Context:** The project needed a source model and licensing strategy aligned with its commercial goals.
- **Alternatives:** Open source (MIT/GPL); public source with paid license; fully proprietary.
- **Rationale:** Private source allows commercial flexibility without competing with free redistribution. A permanent free edition maintains the project's accessibility and serves as the acquisition channel for paid upgrades. This model supports sustainable development without relying on venture funding or enterprise sales.
- **Consequences:** No community contributions. No public code review. All development is internal. The free edition must remain genuinely useful to maintain trust.

---

## Decision 9: Reliability Over Feature Velocity

- **Date:** 2026-06-22 (foundational, reaffirmed regularly)
- **Status:** Active
- **Context:** The application protects users' game saves — data with emotional and time value that cannot be replaced.
- **Alternatives:** Ship features faster, fix bugs when reported.
- **Rationale:** A backup tool that loses data is worse than no backup tool. Every feature must prove it handles failure before it ships. This principle governs code review, testing (including failure injection tests), and release criteria. It is the project's most important priority.
- **Consequences:** Slightly slower feature delivery. Higher testing burden (all 153 tests must pass, including failure injection scenarios). Restore pipeline is tested with the same rigor as sync. Error handling is a first-class concern, not an afterthought.
