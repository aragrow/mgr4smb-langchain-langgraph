"""LangGraph shared state for the sandbox.

Narrower surface than the mgr4smb AgentState — only the fields the
sandbox needs for OTP + passkey verification.
"""

from __future__ import annotations

from typing import Annotated

from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state flowing through the orchestrator → specialist graph.

    `messages` and `remaining_steps` are required by
    langgraph.prebuilt.create_react_agent. The remaining fields are
    our own — they persist across turns via the checkpointer, so we
    can flip `is_verified` from /dev/force-verify or from the
    /chat post-processing step after a VERIFIED reply.
    """

    messages: Annotated[list, add_messages]
    remaining_steps: RemainingSteps
    session_id: str
    user_email: str
    is_verified: bool            # set True after a successful OTP verify
