"""Custom exception hierarchy for the sandbox.

Minimal — only what this project needs. Modeled after mgr4smb.exceptions
but stripped of GHL/Jobber/Mongo-specific subclasses.
"""


class SandboxError(Exception):
    """Base exception for all sandbox errors."""


# --- Auth --------------------------------------------------------------------


class AuthError(SandboxError):
    """JWT validation or client_id lookup failure."""


class TokenExpiredError(AuthError):
    """JWT token has expired."""


class InvalidClientError(AuthError):
    """client_id not found or disabled."""


# --- External APIs -----------------------------------------------------------


class GHLAPIError(SandboxError):
    """GoHighLevel REST API error. Carries HTTP status + short response body."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"GHL {status_code}: {detail}")


class JobberAPIError(SandboxError):
    """Jobber GraphQL/REST error. Carries HTTP status + short detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Jobber {status_code}: {detail}")


# --- Config ------------------------------------------------------------------


class ConfigError(SandboxError):
    """Missing or invalid configuration."""
