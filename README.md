# SaveSync

**Never lose your game saves again.**

Hundreds of hours of progress can disappear because of a corrupted file, a failed SSD, or a Windows reinstall. SaveSync quietly protects your saves so you can spend your time playing instead of worrying about backups.

[Download v2.4.0-beta1](https://github.com/MohamedHussien-zseeker/SaveSync/releases/tag/v2.4.0-beta1) · [Release Notes](docs/RELEASE_NOTES.md) · [Beta Status](docs/BETA_STATUS.md)

> ⚠ This is beta software. See [docs/BETA_STATUS.md](docs/BETA_STATUS.md) for known limitations and what to expect.
>
> SaveSync isn't code-signed yet, so Windows SmartScreen may display a warning. This is expected for independent software.

---

## Why SaveSync?

- **Never lose your progress.** Automatic backups mean you always have a recent copy of your saves.
- **Restore in minutes.** Recovering after reinstalling Windows takes one click.
- **Your files, your control.** Local backups need no account, no internet, no sign-up.
- **Works with your cloud.** Dropbox, Google Drive, and OneDrive — use the storage you already have.
- **Built to be trustworthy.** Restore is tested as carefully as backup. Errors are never silent.
- **Lightweight.** One small executable, nothing to install. Runs on any Windows PC.

**SaveSync never uploads your files or diagnostics automatically. If you choose to report a problem, you decide what information to share.**

### Why not just copy files manually?

A manual backup works — until you forget, or the copy is corrupted and you don't notice. SaveSync:

- **Watches automatically.** No need to remember. Changes are detected and backed up.
- **Verifies every copy.** SHA-256 checksums confirm files are intact, not just present.
- **Supports one-click restore.** Recovering after data loss takes seconds, not hours.
- **Logs everything.** If something goes wrong, you'll know what and when.
- **Restores with confidence.** The restore pipeline is tested as rigorously as sync.

---

## Quick Start

1. **Download** SaveSync.exe from the [latest release](https://github.com/MohamedHussien-zseeker/SaveSync/releases/latest).
2. **Launch it** — the main window opens with a Default profile.
3. **Choose your save folder** — click "Add Folder" and select your game's save directory.
4. **Choose a backup destination** — pick a local folder, external drive, or USB stick.
5. **Click Sync Now** — your saves are copied and verified.

Setup takes 30 seconds. After that, SaveSync watches for changes and keeps your backup current.

*To back up to a cloud provider: open the Accounts tab and connect your Dropbox, Google Drive, or OneDrive account. (Cloud providers require your own app credentials — see the setup guide.)*

---

## What People Use It For

- Protecting saves from games that Steam Cloud doesn't cover
- Backing up emulator save states and memory cards
- Keeping mod configurations safe across reinstalls
- Syncing progress between multiple PCs via cloud storage

---

## Screenshots

*(Placeholder: main window, sync in progress, restore dialog, settings)*

---

## System Requirements

**Windows:** 7, 8, 10, 11 (64-bit)
**Linux:** Development builds available
**No dependencies** — the executable contains everything it needs.

---

## Documentation

New user?
    README → [Quick Start](#quick-start) above

Developer?
    [ARCHITECTURE](docs/ARCHITECTURE.md) → [DESIGN_PRINCIPLES](docs/DESIGN_PRINCIPLES.md) → [DECISIONS](DECISIONS.md) → [SECURITY](docs/SECURITY.md)

Roadmap?
    [PRODUCT_STRATEGY](docs/PRODUCT_STRATEGY.md) → [VISION](docs/VISION.md)

Beta tester?
    [BETA_STATUS](docs/BETA_STATUS.md)

---

## License

Proprietary. All rights reserved.
