"""AUTHENTICATOR_AGENT — identity verification via email OTP.

Called by the orchestrator whenever a sensitive action needs the caller's
identity confirmed. Flow:

  Step 1 — send a 6-digit OTP (once per session) via GHL's workflow.
  Step 2 — verify the code (max 3 attempts).
  Step 3 — escalate: reply starts with UNVERIFIED and ends with the
           literal token CONVERSATION_TERMINATED. The orchestrator
           watches for that token to lock the session.

The system prompt lives in sandbox.prompts.authenticator.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.authenticator import SYSTEM_PROMPT
from sandbox.tools.send_otp import send_otp
from sandbox.tools.verify_otp import verify_otp


TOOLS = [send_otp, verify_otp]


def build():
    """Return a compiled react agent for AUTHENTICATOR_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
