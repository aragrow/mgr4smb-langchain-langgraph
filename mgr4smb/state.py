"""LangGraph shared state definition — single source of truth.

All agents read and write to the same AgentState. This is the ONLY place
AgentState is defined; every other module imports it from here.
"""

from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Shared state flowing through all nodes in the graph."""

    messages: Annotated[list, add_messages]  # SHARED — all agents read/write
    client_id: str              # Authenticated client (from JWT)
    session_id: str             # Conversation session ID
    contact_id: str             # GHL contact ID (cached after first lookup)
    user_email: str
    user_phone: str
    user_timezone: str
    user_name: str
    is_existing_contact: bool
    is_verified: bool           # OTP verified — persists for session
