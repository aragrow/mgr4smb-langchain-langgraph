"""Helpers for building agent nodes and wrapping agents as tools.

Parent agents (booking, ghl_support, jobber_support, orchestrator) need to
invoke child agents as tools. The child agent is a compiled LangGraph
StateGraph; this helper wraps it in a @tool-decorated function whose name
matches what the parent's SYSTEM_PROMPT expects (e.g. "greeting_agent").

The wrapper uses InjectedState so the sub-agent sees the parent's full
conversation history. This is critical for OTP persistence: when booking
delegates to otp_agent for identity verification AFTER a previous agent has
already verified the user in this session, otp_agent needs to see the
earlier "VERIFIED" message and skip re-verification.
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

    The parent agent's LLM will call this tool by name and pass a delegation
    message. The wrapper:
      1. Reads the parent's full messages history via InjectedState.
      2. Appends a new HumanMessage with the delegation instruction.
      3. Runs the sub-agent with this combined history.
      4. Returns the final AI message content as a string, which becomes a
         ToolMessage in the parent's conversation.

    Passing the full history preserves cross-agent context — notably the OTP
    VERIFIED marker, the user's email/phone, and any earlier sub-agent
    responses.
    """

    @tool(name, description=description)
    def _invoke(instruction: str, state: Annotated[dict, InjectedState]) -> str:
        parent_messages = list(state.get("messages", []))

        # Strip any trailing AIMessages that have unresolved tool_calls.
        # The in-flight delegation (the AIMessage whose tool_call we are
        # currently processing) would cause LangGraph to complain about a
        # tool_call with no matching ToolMessage when the sub-agent runs.
        while parent_messages:
            last = parent_messages[-1]
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                parent_messages.pop()
                continue
            break

        # Append the delegation instruction as a fresh human message so the
        # sub-agent's react loop has a clear "current task".
        delegation = HumanMessage(
            content=f"[Delegation from parent agent — {name}]\n{instruction}"
        )
        result = agent.invoke({"messages": parent_messages + [delegation]})
        return _last_ai_text(result.get("messages", []))

    return _invoke
