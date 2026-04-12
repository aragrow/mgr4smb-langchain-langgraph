"""Helpers for building agent nodes and wrapping agents as tools.

Parent agents (booking, ghl_support, jobber_support, orchestrator) need to
invoke child agents as tools. The child agent is a compiled LangGraph
StateGraph; this helper wraps it in a @tool-decorated function whose name
matches what the parent's SYSTEM_PROMPT expects (e.g. "greeting_agent").
"""

from langchain_core.tools import StructuredTool


def agent_as_tool(agent, name: str, description: str):
    """Wrap a compiled agent as a LangChain tool.

    The parent agent's LLM will call this by name (e.g. "greeting_agent") and
    pass a message describing what it wants the sub-agent to do. The sub-agent
    runs its full react loop and returns the final AI message content.
    """

    def _invoke(message: str) -> str:
        result = agent.invoke({"messages": [("user", message)]})
        final_messages = result.get("messages", [])
        if not final_messages:
            return "(sub-agent returned no messages)"
        # Find last AI message
        for msg in reversed(final_messages):
            content = getattr(msg, "content", None)
            if content:
                return content
        return "(sub-agent produced no text output)"

    return StructuredTool.from_function(
        func=_invoke,
        name=name,
        description=description,
    )
