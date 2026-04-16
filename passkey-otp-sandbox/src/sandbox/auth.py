"""JWT validation for the sandbox.

Stripped-down version of mgr4smb/auth.py. The sandbox has ONE known
client — DEV_CLIENT_ID from .env — so we skip the clients.json file
entirely and just check that the token's client_id claim matches.
"""

from __future__ import annotations

import logging
import time

import jwt

from sandbox.config import settings
from sandbox.exceptions import AuthError, InvalidClientError, TokenExpiredError

logger = logging.getLogger(__name__)


def verify_token(token: str) -> str:
    """Verify a JWT and return the client_id claim."""
    if not token:
        raise AuthError("Missing token")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid token: {e}") from e

    client_id = (payload.get("client_id") or "").strip()
    if not client_id:
        raise AuthError("Token missing client_id claim")

    if client_id != settings.dev_client_id:
        logger.warning("Unknown client_id in JWT", extra={"client_id": client_id[:8]})
        raise InvalidClientError("Unknown client_id")

    return client_id


def issue_token(client_id: str = "", expires_in_days: int = 365) -> str:
    """Mint a JWT for a dev client. Defaults to settings.dev_client_id."""
    cid = client_id or settings.dev_client_id
    now = int(time.time())
    payload = {
        "client_id": cid,
        "iat": now,
        "exp": now + (expires_in_days * 86400),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
