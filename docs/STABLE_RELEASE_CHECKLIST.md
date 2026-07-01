# Stable Release Checklist

All items must be checked before promoting v2.4.0-beta1 to v2.4.0 stable.

---

## Issues

- [ ] No unresolved P0 issues (data loss, crash, unrecoverable error)
- [ ] No unresolved P1 issues (broken workflow, incorrect behavior)
- [ ] All known limitations documented and acknowledged by testers

## Testing

- [ ] Cloud OAuth end-to-end validated on real Windows for Dropbox
- [ ] Cloud OAuth end-to-end validated on real Windows for Google Drive
- [ ] Cloud OAuth end-to-end validated on real Windows for OneDrive
- [ ] Full manual test pass completed on Windows 10
- [ ] Full manual test pass completed on Windows 11
- [ ] All 153 automated tests passing on Linux
- [ ] Failure injection tests pass on Windows EXE
- [ ] Stress test passes (concurrent file changes, cancellation, restart)

## Feedback

- [ ] Cold-read test completed — first-time user can install and run using README only
- [ ] Cold-read feedback incorporated into documentation
- [ ] At least 5 external testers completed a sync and restore
- [ ] Tester feedback reviewed and categorized

## Release

- [ ] Installer tested (clean install, upgrade, uninstall)
- [ ] SHA-256 checksums published for all artifacts
- [ ] Release notes finalized
- [ ] Known limitations documented in release notes
- [ ] Git tag pushed (`v2.4.0`)
- [ ] GitHub Release published with all artifacts attached

## Documentation

- [ ] README reviewed and up to date
- [ ] BETA_STATUS.md finalized (remove "Pre-release" banner)
- [ ] ROADMAP.md updated for stable
