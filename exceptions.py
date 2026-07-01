"""SaveSync error hierarchy with stable error codes.

Each exception carries:
  - error_code: stable code for diagnostics (e.g. SS2003)
  - message: user-facing summary
  - diagnostic: technical detail written to logs
"""


class SaveSyncError(Exception):
    """Base exception for all SaveSync errors."""

    error_code: str = "SS0000"
    message: str = "An unexpected error occurred."
    diagnostic: str = ""

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if message:
            self.message = message
        if diagnostic:
            self.diagnostic = diagnostic
        if error_code:
            self.error_code = error_code
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [f"[{self.error_code}] {self.message}"]
        if self.diagnostic:
            parts.append(f" ({self.diagnostic})")
        return "".join(parts)


class AuthError(SaveSyncError):
    """Authentication or token failures."""

    error_code: str = "SS1000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "Authentication failed. Please sign in again."
        super().__init__(message, diagnostic, error_code or self.error_code)


class ProviderError(SaveSyncError):
    """Cloud provider connection or operation failures."""

    error_code: str = "SS2000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "Cloud provider operation failed."
        super().__init__(message, diagnostic, error_code or self.error_code)


class SyncError(SaveSyncError):
    """File synchronization failures."""

    error_code: str = "SS3000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "Sync operation failed."
        super().__init__(message, diagnostic, error_code or self.error_code)


class VerificationError(SaveSyncError):
    """Checksum or integrity verification failures."""

    error_code: str = "SS4000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "File integrity check failed."
        super().__init__(message, diagnostic, error_code or self.error_code)


class ConflictError(SaveSyncError):
    """Sync conflict between local and remote."""

    error_code: str = "SS5000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "A sync conflict was detected and could not be resolved."
        super().__init__(message, diagnostic, error_code or self.error_code)


class ConfigError(SaveSyncError):
    """Configuration or setup errors."""

    error_code: str = "SS6000"

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        if not message:
            message = "Configuration is invalid or missing."
        super().__init__(message, diagnostic, error_code or self.error_code)


class OperationCancelled(SaveSyncError):
    """Operation was cancelled by the user."""

    error_code: str = "SS7000"
    message: str = "Operation cancelled."

    def __init__(self, message: str = "", diagnostic: str = "",
                 error_code: str = ""):
        super().__init__(message or self.message,
                         diagnostic,
                         error_code or self.error_code)
