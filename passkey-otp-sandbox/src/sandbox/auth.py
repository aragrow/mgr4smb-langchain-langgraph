"""JWT validation + client_id registry lookup.

Ported from mgr4smb/auth.py. The sandbox now uses clients.json for
multi-tenant JWT auth — same pattern as production. Each client has
a UUID client_id, a name, an enabled flag, and a created_at
timestamp. Disabling a client immediately rejects all their JWTs
without rotating JWT_SECRET.

clients.json structure:
  {
    "clients": [
      { "client_id": "<uuid>", "name": "...", "enabled": true, "created_at": "..." }
    ]
  }
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import jwt

from sandbox.config import settings
from sandbox.exceptions import (
    AuthError,
    ConfigError,
    InvalidClientError,
    TokenExpiredError,
)

logger = logging.getLogger(__name__)


def _load_clients() -> list[dict]:
    """Read clients.json from the configured path. Returns [] if missing."""
    path: Path = settings.clients_file
    if not path.exists():
        logger.warning("clients.json not found at %s", path)
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("clients", []) or []
    except Exception as e:
        logger.error("Failed to parse clients.json", exc_info=True)
        raise ConfigError(f"Could not read {path}: {e}") from e


def _find_client(client_id: str) -> dict | None:
    for c in _load_clients():
        if c.get("client_id") == client_id:
            return c
    return None


def verify_token(token: str) -> str:
    """Verify a JWT and return the client_id claim.

    Raises:
        TokenExpiredError: token expired.
        AuthError: malformed or signature-invalid token.
        InvalidClientError: client_id not in clients.json or disabled.
    """
    if not token:
        logger.warning("Auth rejected: empty token")
        raise AuthError("Missing token")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        logger.warning("Auth rejected: token expired")
        raise TokenExpiredError("Token expired") from e
    except jwt.InvalidTokenError as e:
        logger.warning("Auth rejected: invalid token", extra={"error": str(e)})
        raise AuthError(f"Invalid token: {e}") from e

    client_id = payload.get("client_id", "").strip()
    if not client_id:
        logger.warning("Auth rejected: token missing client_id claim")
        raise AuthError("Token missing client_id claim")

    client = _find_client(client_id)
    if not client:
        logger.warning(
            "Auth rejected: unknown client",
            extra={"client_id": client_id[:8] + "..."},
        )
        raise InvalidClientError("Unknown client_id")

    if not client.get("enabled", False):
        logger.warning(
            "Auth rejected: client disabled",
            extra={"client_id": client_id[:8] + "..."},
        )
        raise InvalidClientError("Client is disabled")

    logger.debug(
        "Token verified", extra={"client_id": client_id[:8] + "..."}
    )
    return client_id


def issue_token(client_id: str = "", expires_in_days: int = 365) -> str:
    """Mint a JWT for a client_id. Defaults to settings.dev_client_id."""
    cid = client_id or settings.dev_client_id
    now = int(time.time())
    payload = {
        "client_id": cid,
        "iat": now,
        "exp": now + (expires_in_days * 86400),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
