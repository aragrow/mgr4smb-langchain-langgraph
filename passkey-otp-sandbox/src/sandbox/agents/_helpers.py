"""Helpers for wrapping a compiled LangGraph agent as a LangChain tool.

Copied and adapted from mgr4smb/agents/_helpers.py. Uses InjectedState so
the sub-agent sees the parent's full conversation history.
"""

from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState


def _last_ai_text(messages: list) -> str:
    """Return text content of the last AI message, normalising list-of-blocks."""
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(
                blk.get("text", "") if isinstance(blk, dict) else str(blk)
                for blk in content
            )
        if content:
            return content
    return "(sub-agent produced no text output)"


def agent_as_tool(agent, name: str, description: str):
    """Wrap a compiled LangGraph agent as a LangChain tool.

    Passing the full history preserves cross-agent context — notably the
    OTP VERIFIED marker, the user's email, and any earlier sub-agent
    responses. Trailing AIMessages with unresolved tool_calls are stripped
    because their ToolMessage would not exist in the sub-agent's run.
    """

    @tool(name, description=description)
    def _invoke(instruction: str, state: Annotated[dict, InjectedState]) -> str:
        parent_messages = list(state.get("messages", []))

        while parent_messages:
            last = parent_messages[-1]
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                parent_messages.pop()
                continue
            break

        delegation = HumanMessage(
            content=f"[Delegation from parent agent — {name}]\n{instruction}"
        )
        result = agent.invoke({"messages": parent_messages + [delegation]})
        return _last_ai_text(result.get("messages", []))

    return _invoke
