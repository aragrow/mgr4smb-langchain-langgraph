"""LangGraph shared state for the sandbox.

Narrower surface than the mgr4smb AgentState — only the fields the
sandbox needs for OTP + passkey verification.
"""

from __future__ import annotations

from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state flowing through the orchestrator → OTP agent graph."""

    messages: Annotated[list, add_messages]
    session_id: str
    user_email: str
    is_verified: bool            # set True by either OTP or passkey
    is_passkey_verified: bool    # set True only after passkey verify
