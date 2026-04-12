"""Main LangGraph graph assembly.

Builds all 7 agents bottom-up and compiles the orchestrator with a
MongoDBSaver checkpointer so conversations persist per session_id.

Two entry points:
  - build_graph(checkpointer): returns a compiled orchestrator graph
  - run_turn(graph, message, session_id, ...): invokes one turn and returns
    the final AI message content

Typical usage (CLI):
    from mgr4smb.memory import checkpointer_context
    from mgr4smb.graph import build_graph, run_turn

    with checkpointer_context() as cp:
        graph = build_graph(cp)
        response = run_turn(graph, "Hello", session_id="abc-123")

For the API (Phase 9) the checkpointer lives for the lifetime of the app.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage

from mgr4smb.agents import (
    booking,
    general_info,
    ghl_support,
    greeting,
    jobber_support,
    orchestrator,
    otp,
)

logger = logging.getLogger(__name__)


def build_agents() -> dict:
    """Build every agent bottom-up. Returns a dict keyed by agent name.

    The sub-agent references are resolved at build time so the dependency
    graph is explicit:
        otp, greeting, general_info          (leaves)
        jobber_support(otp)                   (mid)
        booking(otp, jobber_support)          (mid)
        ghl_support(otp, booking)             (mid)
        orchestrator(greeting, general_info, booking, ghl_support, jobber_support)
    """
    logger.info("Building agents")

    otp_agent = otp.build()
    greeting_agent = greeting.build()
    general_info_agent = general_info.build()

    jobber_support_agent = jobber_support.build(otp_agent=otp_agent)
    booking_agent = booking.build(
        otp_agent=otp_agent,
        jobber_support_agent=jobber_support_agent,
    )
    ghl_support_agent = ghl_support.build(
        otp_agent=otp_agent,
        booking_agent=booking_agent,
    )
    orchestrator_agent = orchestrator.build(
        greeting_agent=greeting_agent,
        general_info_agent=general_info_agent,
        booking_agent=booking_agent,
        ghl_support_agent=ghl_support_agent,
        jobber_support_agent=jobber_support_agent,
    )

    logger.info("All 7 agents built")
    return {
        "otp": otp_agent,
        "greeting": greeting_agent,
        "general_info": general_info_agent,
        "jobber_support": jobber_support_agent,
        "booking": booking_agent,
        "ghl_support": ghl_support_agent,
        "orchestrator": orchestrator_agent,
    }


def build_graph(checkpointer=None):
    """Build and return the compiled top-level graph (the orchestrator).

    The orchestrator is itself a compiled react agent; its .invoke() starts
    the full delegation chain. We re-compile here ONLY to wire in the
    checkpointer for session persistence, since create_react_agent does not
    expose a way to attach one after construction.

    Args:
        checkpointer: Optional MongoDBSaver (from mgr4smb.memory). If None,
                       conversations will not persist across .invoke() calls.

    Returns:
        A compiled StateGraph. Invoke with:
            graph.invoke(
                {"messages": [("user", "...")]},
                config={"configurable": {"thread_id": session_id}},
            )
    """
    agents = build_agents()
    orchestrator_agent = agents["orchestrator"]

    if checkpointer is not None:
        # create_react_agent returns a compiled StateGraph whose builder is
        # the attached `.builder`. Re-compile that builder with the checkpointer.
        try:
            builder = orchestrator_agent.builder
            graph = builder.compile(checkpointer=checkpointer)
            logger.info("Graph compiled with MongoDB checkpointer")
            return graph
        except AttributeError:
            logger.warning(
                "Orchestrator has no .builder — returning uncheckpointed graph"
            )

    return orchestrator_agent


def run_turn(
    graph,
    message: str,
    session_id: str,
    client_id: str = "",
) -> str:
    """Invoke one turn of the conversation and return the final AI text.

    Args:
        graph: The compiled graph from build_graph().
        message: The user's message for this turn.
        session_id: Stable ID for this conversation — maps to LangGraph
                     thread_id so the checkpointer resumes prior state.
        client_id: Authenticated client (used for logging/tracing context).

    Returns:
        The final AI message text content for this turn.
    """
    config = {"configurable": {"thread_id": session_id}}
    logger.info(
        "Turn started",
        extra={"session_id": session_id, "client_id": client_id},
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )

    # Extract final AI text
    msgs = result.get("messages", [])
    for msg in reversed(msgs):
        if not isinstance(msg, AIMessage):
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(
                blk.get("text", "") if isinstance(blk, dict) else str(blk)
                for blk in content
            )
        if content:
            logger.info(
                "Turn completed",
                extra={"session_id": session_id, "reply_chars": len(content)},
            )
            return content

    return "(no response)"


def get_history(graph, session_id: str) -> list:
    """Return the full message history for a session_id (requires checkpointer)."""
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)
    return state.values.get("messages", []) if state else []
