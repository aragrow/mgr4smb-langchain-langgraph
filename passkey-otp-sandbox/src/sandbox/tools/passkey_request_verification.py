"""Tool: passkey_request_verification — tells the UI to show the passkey
button.

The tool itself does NO WebAuthn work — WebAuthn happens in the browser
(navigator.credentials.get) and is only completed once the user taps the
authenticator. This tool exists so the agent can emit a deterministic
marker ("PASSKEY_REQUESTED") that the chat UI polls for to decide when
to render the "Use passkey" button.

Keeping the browser flow out of the agent loop is intentional: the agent
is stateless tool-calling text; WebAuthn needs DOM APIs and user
gesture, which only the UI has.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def passkey_request_verification(user_email: str) -> str:
    """Signal the UI that the user should tap their registered passkey.

    The tool returns the literal string 'PASSKEY_REQUESTED' — do not
    modify it; the chat UI matches it exactly.
    """
    email = (user_email or "").strip().lower()
    logger.info("passkey_request_verification", extra={"email": email})
    return "PASSKEY_REQUESTED"
