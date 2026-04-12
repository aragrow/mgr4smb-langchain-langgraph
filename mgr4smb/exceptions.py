"""Custom exception hierarchy for mgr4smb.

Every module should raise these instead of bare Exception/ValueError.
FastAPI exception handlers map these to HTTP status codes.
"""


class Mgr4smbError(Exception):
    """Base exception for all project errors."""


# ---------------------------------------------------------------------------
# External API errors
# ---------------------------------------------------------------------------

class ExternalAPIError(Mgr4smbError):
    """Base for all external service failures."""

    def __init__(self, service: str, status_code: int, detail: str):
        self.service = service
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{service} API error {status_code}: {detail}")


class GHLAPIError(ExternalAPIError):
    """GoHighLevel API returned a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        super().__init__("GHL", status_code, detail)


class JobberAPIError(ExternalAPIError):
    """Jobber GraphQL API returned an error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__("Jobber", status_code, detail)


class MongoDBError(Mgr4smbError):
    """MongoDB connection or query failure."""


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------

class AuthError(Mgr4smbError):
    """JWT validation or client_id lookup failure."""


class TokenExpiredError(AuthError):
    """JWT token has expired."""


class InvalidClientError(AuthError):
    """client_id not found or disabled in clients.json."""


# ---------------------------------------------------------------------------
# Agent errors
# ---------------------------------------------------------------------------

class AgentError(Mgr4smbError):
    """An agent failed to produce a valid response."""

    def __init__(self, agent_name: str, detail: str):
        self.agent_name = agent_name
        super().__init__(f"Agent '{agent_name}' failed: {detail}")


# ---------------------------------------------------------------------------
# Tool errors
# ---------------------------------------------------------------------------

class ToolError(Mgr4smbError):
    """A tool invocation failed due to an infrastructure issue."""

    def __init__(self, tool_name: str, detail: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {detail}")


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------

class ConfigError(Mgr4smbError):
    """Missing or invalid configuration."""
