"""AUTHENTICATOR_AGENT — identity verification (passkey + OTP).

Called by the orchestrator whenever a sensitive action needs the caller's
identity confirmed. Tries a passkey first (one tap, no code), falls back
to an email OTP (3 attempts max, then terminates the session).

Flow:
  Step 0  — passkey_status — does this email have a registered passkey?
  Step 0b — if yes: emit PASSKEY_REQUESTED; wait for the browser to hand
            back "Passkey verified" (success) or "Passkey verification
            did not complete…" (fall through to OTP).
  Step 1  — send the 6-digit code (once per session).
  Step 2  — verify the code (max 3 attempts).
  Step 3  — escalate: reply starts with UNVERIFIED and ends with the
            literal token CONVERSATION_TERMINATED. The orchestrator
            watches for that token to lock the session.

The system prompt lives in sandbox.prompts.authenticator.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.authenticator import SYSTEM_PROMPT
from sandbox.tools.passkey_request_verification import passkey_request_verification
from sandbox.tools.passkey_status import passkey_status
from sandbox.tools.send_otp import send_otp
from sandbox.tools.verify_otp import verify_otp


TOOLS = [passkey_status, passkey_request_verification, send_otp, verify_otp]


def build():
    """Return a compiled react agent for AUTHENTICATOR_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
