<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/screenshots/dashboard.png">
  <img alt="SaveSync Dashboard" src="assets/screenshots/dashboard.png" width="100%">
</picture>

# SaveSync

**Automatic backup, synchronization, and restoration for PC game saves.**

SaveSync continuously protects your save files locally or in the cloud so you can recover from crashes, reinstalls, or hardware failures with a single click.

[![Release](https://img.shields.io/badge/release-v2.0.0--rc.1-blue)][release]
[![Python](https://img.shields.io/badge/python-3.12-blue)](#)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey)](#)
[![Tests](https://img.shields.io/badge/tests-192%20passing-brightgreen)](#)
[![License](https://img.shields.io/badge/license-proprietary-darkblue)](#)

---

## Screenshots

| Dashboard | Profiles | Accounts |
|:---:|:---:|:---:|
| ![Dashboard](assets/screenshots/dashboard.png) | ![Profiles](assets/screenshots/profiles.png) | ![Accounts](assets/screenshots/accounts.png) |

| Activity | Settings |
|:---:|:---:|
| ![Activity](assets/screenshots/activity.png) | ![Settings](assets/screenshots/settings.png) |

---

## Features

| Feature | Status |
|---|---|
| Automatic file monitoring | ✅ |
| One-click restore with verification | ✅ |
| SHA-256 integrity checking | ✅ |
| Multiple backup profiles | ✅ |
| Activity log with filtering | ✅ |
| Local folder backup | ✅ |
| External drive support | ✅ |
| Google Drive cloud sync | ✅ |
| Dropbox cloud sync | ✅ |
| OneDrive cloud sync | ✅ |
| Background daemon mode | ✅ |
| Real-time sync progress | ✅ |
| Accessibility compliant (WCAG AA) | ✅ |
| 192 automated tests | ✅ |

## Architecture

```
┌─────────────┐
│   UI Layer  │  CustomTkinter-themed desktop GUI (ttk, Tokyo Night)
├─────────────┤
│   Profiles  │  Named profiles with per-profile watch dirs & providers
├─────────────┤
│ Sync Engine │  Background threads, progress tracking, cancellation
├─────────────┤
│  Storage    │  Local FS  │  Google Drive  │  Dropbox  │  OneDrive
└─────────────┘
```

## Quick Start

1. **Download** SaveSync from the [latest release][release].
2. **Launch it** — the main window opens with a Default profile.
3. **Choose your save folder** — click Add Folder and select your game's save directory.
4. **Choose a backup destination** — pick a local folder, external drive, or connect a cloud provider.
5. **Click Sync Now** — your saves are copied and verified.

Setup takes 30 seconds. After that, SaveSync watches for changes automatically.

## Supported Storage

| Storage | Type | Account Required |
|---|---|---|
| Local folder | Local | No |
| External drive / USB | Local | No |
| Google Drive | Cloud | Yes (BYO credentials) |
| Dropbox | Cloud | Yes (BYO credentials) |
| OneDrive | Cloud | Yes (BYO credentials) |

## Quality

| Metric | Value |
|---|---|
| Automated tests | 192 passing |
| Test type | Workflow (CRUD, sync, restore, lifecycle) |
| Accessibility checklist | 38 items, all passing |
| GUI testing | Headless Xvfb, all DPIs (96–192) |
| Test determinism | No network, no credentials, no `sleep()` |

## Documentation

| Audience | Docs |
|---|---|
| New users | [Quick Start](#quick-start) |
| Developers | [Architecture](docs/ARCHITECTURE.md) · [Design Principles](docs/DESIGN_PRINCIPLES.md) · [Decisions](docs/DECISIONS.md) |
| Beta testers | [Release Notes](docs/RELEASE_NOTES.md) · [Known Issues](docs/BETA_STATUS.md) |

## System Requirements

- **Windows:** 7, 8, 10, 11 (64-bit)
- **Linux:** Development builds available
- **No dependencies** — single executable, nothing to install

## Known Limitations

- Cloud providers require your own OAuth app credentials (setup guide included)
- Windows installer and code signing are pending the final release
- See the [release notes](docs/RELEASE_NOTES.md) for the complete list

## License

Proprietary. All rights reserved.

[release]: https://github.com/MohamedHussien-zseeker/SaveSync/releases/tag/v2.0.0-rc.1
