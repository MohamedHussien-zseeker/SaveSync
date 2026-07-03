# Release Validation Checklist — SaveSync v2.0.0-rc.2

## Build Validation

| Item | Status | Notes |
|------|--------|-------|
| PyInstaller build completes without errors | ✅ Pass | `pyinstaller SaveSync.spec` clean |
| Binary is executable | ✅ Pass | ELF 64-bit LSB executable, stripped |
| Binary size is reasonable | ✅ Pass | ~13 MB single-file executable |
| `--version` reports correct version | ✅ Pass | `SaveSync v2.0.0-rc.2` |
| `--help` lists all options | ✅ Pass | 6 flags documented |
| `--self-test` passes | ✅ Pass | Validates core imports |
| `--gui-smoke-test` passes | ✅ Pass | All tabs render without blocking |
| All source modules bundled | ✅ Pass | core, providers, state, logging_system, cloud, config_sync, credential_store, exceptions, transfer |
| Optional cloud deps handled gracefully | ✅ Pass | googleapiclient/dropbox/keyring missing — delayed imports, no crash |
| Binary dependencies minimal | ✅ Pass | Only libdl, libz, libpthread, libc |

## Artifact Integrity

| Item | Status | Notes |
|------|--------|-------|
| SHA-256 checksum recorded | ✅ Pass | `54a24b90e99621cc6edafba7f880645ba600327d077cdd204782d9adcc28dd67` |
| Checksums file created | ✅ Pass | `dist/checksums.txt` |
| Build is reproducible from source | ✅ ⚠️ | Same spec + source → same bytecode; binary may vary by PyInstaller/libc version |

## Runtime Validation (Linux)

| Item | Status | Notes |
|------|--------|-------|
| Smoke test passes at 100% DPI | ✅ Pass | Xvfb 96 DPI |
| Smoke test passes at 150% DPI | ✅ Pass | Xvfb 144 DPI |
| Smoke test passes at 200% DPI | ✅ Pass | Xvfb 192 DPI |
| Full test suite (193 tests) | ✅ Pass | All pass at 150% DPI |
| Version works without DISPLAY | ✅ Pass | No X server needed for `--version` |
| Help works without DISPLAY | ✅ Pass | No X server needed for `--help` |

## Windows CI Validation

| Item | Status | Notes |
|------|--------|-------|
| PyInstaller EXE built without errors | ⏳ Pending | CI builds `SaveSync.exe` from spec |
| PE header valid (MZ magic) | ⏳ Pending | Static PE validation |
| `--version` in CI | ⏳ Pending | Verifies EXE runs, reports version |
| `--self-test` in CI | ⏳ Pending | Validates all module imports/init |
| EXE artifact uploaded | ⏳ Pending | Available for download + manual test |
| SHA-256 checksum recorded | ⏳ Pending | Per-artifact checksum |

## Windows Manual Validation (Release Gate)

| Item | Status | Notes |
|------|--------|-------|
| Defender does not block EXE | ⏳ Pending | Must be verified on clean Windows host |
| GUI launches from packaged EXE | ⏳ Pending | Double-click opens CTk window |
| All sidebar pages render | ⏳ Pending | Home, Games, Cloud, Activity, Settings |
| `--gui-smoke-test` passes | ⏳ Pending | Headless render on Windows (requires display) |
| Screenshots regenerated from validated EXE | ⏳ Pending | Replace RC1 screenshots |

## Known Gaps (Non-Blocking)

| Item | Notes |
|------|-------|
| Windows installer | Not yet created; EXE is standalone |
| Code signing | Requires certificate; not available in current env |
| Auto-update mechanism | Not yet implemented |
