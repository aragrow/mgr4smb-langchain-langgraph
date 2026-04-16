"""Tool: passkey_status — does this user have a passkey on file?

Returns the literal string "REGISTERED" or "NONE" so the agent prompt can
branch on it cleanly. No other metadata is exposed — the tool must not
leak information about which authenticator the user used.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from sandbox.webauthn import storage

logger = logging.getLogger(__name__)


@tool
def passkey_status(user_email: str) -> str:
    """Return 'REGISTERED' if the user has at least one passkey on file,
    otherwise 'NONE'."""
    email = (user_email or "").strip().lower()
    if not email:
        return "NONE"
    n = storage.count_for(email)
    logger.info("passkey_status", extra={"email": email, "count": n})
    return "REGISTERED" if n > 0 else "NONE"
