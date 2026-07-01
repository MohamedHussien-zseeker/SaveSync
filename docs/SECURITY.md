# Security Policy

---

## For Users

### Local-First Philosophy

SaveSync works fully offline. All backups are stored wherever you choose — a local folder, an external drive, or a USB stick. Cloud storage is optional and never required.

### Credential Handling

- OAuth tokens are stored using your operating system's credential API (DPAPI on Windows).
- Tokens are never written to log files, configuration files, or the application's data directory.
- Tokens are never transmitted except directly to the provider's API during authenticated requests.
- SaveSync does not operate its own servers and never receives your credentials.

### What SaveSync Collects

Nothing. SaveSync contains no telemetry, analytics, crash reporting, or usage tracking of any kind. The application never makes network connections except to cloud provider APIs you have explicitly configured.

### What SaveSync Does Not Do

- No phone-home calls.
- No analytics or usage data collection.
- No bundled third-party software.
- No background processes that run when the application is closed (unless you enable system tray mode).
- No modification of game files. SaveSync reads your save folders and writes to backup destinations. It never alters source files.

### Reporting a Security Vulnerability

If you discover a security vulnerability in SaveSync:

1. **Do not** open a public GitHub issue.
2. Email your report to [security@savesync.app — pending].
3. Include a description of the issue, steps to reproduce, and the version you tested.
4. You should receive an acknowledgment within 72 hours.
5. We aim to release a fix within 30 days of confirmation.

We practice responsible disclosure and will coordinate with you on the timeline.

### Supported Versions

| Version | Support |
|---------|---------|
| v2.4.x (beta) | Security issues reviewed and addressed, no SLA |
| Older versions | No longer supported |

---

## For Developers

### Threat Model

- **Local attacker with file system access** — Credential storage relies on OS-level protection (DPAPI). Config files do not contain secrets.
- **Network attacker** — All provider API communications use HTTPS. OAuth 2.0 flows use PKCE to prevent authorization code interception.
- **Supply chain** — The application uses Python standard library only. No third-party packages are bundled or fetched at runtime.
- **Physical device access** — Assumes the OS user account boundary is trusted. Standard OS file permissions apply.

### Security Assumptions

- The user's operating system and Python runtime are not compromised.
- The user's cloud provider API endpoints are trusted and properly authenticated via TLS.
- The user's local file system correctly enforces file permissions.
- The user's OAuth app credentials (client ID and secret) are kept confidential and not shared.

### Safe Coding Expectations

- **No secrets in logs.** Credentials, tokens, and paths containing user-identifiable information must be redacted before logging.
- **No eval/exec.** Dynamic code execution is prohibited.
- **No insecure deserialization.** JSON parsing uses safe parsers only. No pickle.
- **Least privilege.** File operations use the minimum necessary permissions. Temporary files are created with restrictive permissions.
- **Input validation.** All user-provided paths are sanitized. Path traversal attacks are prevented by resolving paths against allowed base directories.
- **Fail closed.** When verification cannot be completed, the operation is treated as failed. Partial transfers leave the destination unchanged.

### Dependency Policy

SaveSync uses Python standard library exclusively. This is a deliberate security measure: there are no external packages to audit, no transitive dependencies, and no risk of a compromised PyPI package affecting the application.

Should a future version adopt external dependencies, each will be reviewed for:

- Maintenance status and security track record
- License compatibility
- Necessity (can the feature be implemented with stdlib?)
- Auditability of the dependency's code

### Release Verification

- Every release includes a `SHA256SUMS.txt` file with checksums for all artifacts.
- Checksums are published alongside the release and should be verified before use.
- Future releases may include code signing once a signing certificate is obtained.
- The canonical build environment is Docker-based and documented in `SETUP.md`, ensuring reproducible builds.
