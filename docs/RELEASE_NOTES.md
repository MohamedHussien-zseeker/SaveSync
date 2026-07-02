# SaveSync 2.0.0-rc.1 — Release Candidate

**Never lose your game saves again.**

SaveSync automatically backs up, syncs, and restores your PC game saves so you can recover from crashes, reinstalls, or hardware failures with a single click.

> **Version note:** SaveSync has been extensively rewritten since the earlier experimental builds. Version 2.0.0 starts a new release line and supersedes the previous `v2.4.0-beta1` releases.

---

## What's New

### Modern interface
Complete visual redesign with a dark Tokyo Night theme, clearer navigation, and real-time progress tracking during backups.

### Faster, more reliable sync
Background sync engine with live progress bars, file-level status updates, and safe cancellation. No more guessing whether your backup is working.

### One-click restore
Restore your saves from any backup point with automatic SHA-256 verification. If the file isn't identical to the original, SaveSync tells you before it restores.

### Better keyboard accessibility
Every dialog can be closed with Escape, all buttons are reachable by keyboard, and focus indicators are clearly visible.

### Deterministic testing
Hundreds of automated tests verify profile management, cloud connections, sync/restore workflows, and application lifecycle — every build, every time.

### Expanded storage support

| Storage | Details |
|---|---|
| Local folders | Built-in, no account needed |
| External drives / USB | Plug and play |
| Google Drive | Bring your own OAuth credentials |
| Dropbox | Bring your own app key |
| OneDrive | Bring your own app registration |

---

## Screenshots

| Dashboard | Profiles | Accounts |
|:---:|:---:|:---:|
| ![Dashboard](https://github.com/MohamedHussien-zseeker/SaveSync/releases/download/v2.0.0-rc.1/dashboard.png) | ![Profiles](https://github.com/MohamedHussien-zseeker/SaveSync/releases/download/v2.0.0-rc.1/profiles.png) | ![Accounts](https://github.com/MohamedHussien-zseeker/SaveSync/releases/download/v2.0.0-rc.1/accounts.png) |

| Activity | Settings |
|:---:|:---:|
| ![Activity](https://github.com/MohamedHussien-zseeker/SaveSync/releases/download/v2.0.0-rc.1/activity.png) | ![Settings](https://github.com/MohamedHussien-zseeker/SaveSync/releases/download/v2.0.0-rc.1/settings.png) |

---

## Download

**Windows build:** Coming soon. A GitHub Actions workflow (`.github/workflows/build-windows.yml`) is ready to produce the Windows EXE automatically. Push a tag and the workflow builds, signs, and uploads it. Windows validation is the final gate before `v2.0.0` stable. This RC validates the Linux build only.

**Linux x64:** `SaveSync-v2.0.0-rc.1-linux-x64` (included below)

*No installation required — just download, chmod +x, and run.*

---

## Quick Start

1. Download SaveSync from the assets below.
2. Launch it. The main window opens with a Default profile.
3. Click Add Folder and select your game's save directory.
4. Choose a backup destination (local folder, external drive, or cloud provider).
5. Click Sync Now. Your saves are copied and verified.

*Setup takes about 30 seconds. After that, SaveSync monitors your saves automatically.*

---

## Known Limitations (Pre-Release)

- Windows installer and code signing are in progress
- Windows Defender SmartScreen may show a warning (expected for unsigned software)
- Cloud providers require your own OAuth application credentials
- See the full [known issues list](https://github.com/MohamedHussien-zseeker/SaveSync/issues)

---

## Technical Details

For developers and contributors:

- **Test suite:** 192 automated workflow tests, all passing
- **Accessibility:** WCAG AA compliant (38-item audit)
- **Build:** Reproducible PyInstaller pipeline
- **Architecture:** UI → Profiles → Sync Engine → Storage (local + cloud)
- **Technologies:** Python, tkinter/ttk, Tokyo Night theme
