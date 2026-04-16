"""Shared Jobber GraphQL client with OAuth2 token refresh.

Ported from mgr4smb/tools/jobber_client.py. Handles:
  - Reading access/refresh tokens from the configured tokens file.
  - In-process token cache for fast reuse.
  - Automatic refresh on 401 / GraphQL auth error.
  - Token rotation (Jobber invalidates old refresh_tokens on use).
  - Connection pooling via a shared httpx.Client with 10s/5s timeouts.

The sandbox defaults settings.jobber_tokens_file to the PARENT
project's .tokens.json so both mgr4smb and the sandbox share a single
OAuth lifecycle. Jobber only allows one active refresh token per app,
so two independent files would invalidate each other on rotation.
"""

import json
import logging

import httpx

from sandbox.config import settings
from sandbox.exceptions import JobberAPIError

logger = logging.getLogger(__name__)

JOBBER_GRAPHQL_URL = "https://api.getjobber.com/api/graphql"
JOBBER_TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
JOBBER_VERSION = "2026-03-10"

_TOKEN_CACHE: dict[str, str] = {}
_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    """Return a singleton httpx.Client for Jobber requests (no auth
    headers — those are per-request because the token may refresh).
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))
        logger.info("Jobber httpx.Client initialised")
    return _client


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-JOBBER-GRAPHQL-VERSION": JOBBER_VERSION,
    }


def _load_token_file() -> dict:
    try:
        return json.loads(settings.jobber_tokens_file.read_text())
    except Exception:
        return {}


def _save_token_file(access_token: str, refresh_token: str) -> None:
    try:
        settings.jobber_tokens_file.write_text(
            json.dumps(
                {"access_token": access_token, "refresh_token": refresh_token},
                indent=2,
            )
        )
    except Exception:
        logger.warning("Failed to write %s", settings.jobber_tokens_file)


def _active_token() -> str:
    cached = _TOKEN_CACHE.get("access_token")
    if cached:
        return cached

    entry = _load_token_file()
    if entry.get("access_token"):
        _TOKEN_CACHE["access_token"] = entry["access_token"]
        return entry["access_token"]

    raise JobberAPIError(
        401,
        f"No access_token found in {settings.jobber_tokens_file}. "
        "Authorise the Jobber app and write initial tokens to the file.",
    )


def _refresh_token() -> str:
    entry = _load_token_file()
    refresh_token = entry.get("refresh_token")
    if not refresh_token:
        raise JobberAPIError(
            401,
            f"No refresh_token in {settings.jobber_tokens_file}. "
            "Re-authorise the Jobber app.",
        )

    try:
        resp = get_client().post(
            JOBBER_TOKEN_URL,
            json={
                "client_id": settings.jobber_client_id,
                "client_secret": settings.jobber_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Jobber token refresh failed",
            extra={"status": e.response.status_code, "body": e.response.text[:200]},
        )
        raise JobberAPIError(e.response.status_code, "Token refresh failed") from e

    payload = resp.json()
    new_access = payload["access_token"]
    new_refresh = payload.get("refresh_token", refresh_token)

    _TOKEN_CACHE["access_token"] = new_access
    _save_token_file(new_access, new_refresh)
    logger.info("Jobber token refreshed successfully")
    return new_access


def _is_auth_error(resp: httpx.Response) -> bool:
    if resp.status_code == 401:
        return True
    try:
        errors = resp.json().get("errors", [])
        for e in errors:
            s = str(e).lower()
            if "unauthorized" in s or "unauthenticated" in s or "not authenticated" in s:
                return True
    except Exception:
        pass
    return False


def execute(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query or mutation with automatic token refresh.

    Returns the full JSON response. Raises JobberAPIError on failure.
    """
    def _post(token: str) -> httpx.Response:
        return get_client().post(
            JOBBER_GRAPHQL_URL,
            headers=_headers(token),
            json={"query": query, "variables": variables or {}},
        )

    try:
        token = _active_token()
        resp = _post(token)

        if _is_auth_error(resp):
            logger.info("Auth error — refreshing Jobber token and retrying")
            token = _refresh_token()
            resp = _post(token)

        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Jobber GraphQL error",
            extra={"status": e.response.status_code, "body": e.response.text[:200]},
        )
        raise JobberAPIError(e.response.status_code, e.response.text[:200]) from e
    except httpx.ConnectError as e:
        logger.error("Jobber unreachable", extra={"error": str(e)})
        raise JobberAPIError(503, "Service unreachable") from e

    data = resp.json()
    if "errors" in data and data["errors"]:
        detail = str(data["errors"][:3])[:300]
        logger.error("Jobber GraphQL errors", extra={"detail": detail})
        raise JobberAPIError(400, detail)

    return data
