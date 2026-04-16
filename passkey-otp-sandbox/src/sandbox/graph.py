"""LangGraph assembly for the sandbox.

Two entry points:
  - build_graph(checkpointer=None) → compiled orchestrator graph
  - run_turn(graph, message, session_id) → invokes one turn; returns AI text

run_turn snapshots the message count BEFORE invoking so an empty turn
response does not silently recycle a stale AI message from a previous
turn. Same technique as mgr4smb/graph.py.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from sandbox.agents import account as acct_mod
from sandbox.agents import authenticator as auth_mod
from sandbox.agents import client_notifier as client_notifier_mod
from sandbox.agents import general_info as ginfo_mod
from sandbox.agents import greeting as greet_mod
from sandbox.agents import orchestrator as orch_mod
from sandbox.agents import reschedule as resched_mod
from sandbox.agents import vendor_notifier as vendor_notifier_mod

logger = logging.getLogger(__name__)


def build_graph(checkpointer=None):
    """Build the orchestrator graph and compile it with a checkpointer.

    The sandbox defaults to LangGraph's InMemorySaver so run_turn's
    `graph.get_state(config)` works (snapshotting message count requires
    a checkpointer). For production you'd pass a durable checkpointer.
    """
    auth_agent = auth_mod.build()
    ginfo_agent = ginfo_mod.build()
    greet_agent = greet_mod.build()
    acct_agent = acct_mod.build()
    # Notifier agents are internal — built once, then wired into
    # reschedule_agent as sub-tools.
    vendor_notifier_agent = vendor_notifier_mod.build()
    client_notifier_agent = client_notifier_mod.build()
    resched_agent = resched_mod.build(
        vendor_notifier_agent=vendor_notifier_agent,
        client_notifier_agent=client_notifier_agent,
    )
    orch_agent = orch_mod.build(
        greeter_agent=greet_agent,
        general_info_agent=ginfo_agent,
        authenticator_agent=auth_agent,
        account_agent=acct_agent,
        reschedule_agent=resched_agent,
    )

    if checkpointer is None:
        checkpointer = InMemorySaver()

    try:
        builder = orch_agent.builder
        graph = builder.compile(checkpointer=checkpointer)
        logger.info("Graph compiled with checkpointer=%s", type(checkpointer).__name__)
        return graph
    except AttributeError:
        logger.warning("Orchestrator has no .builder — returning uncheckpointed graph")
        return orch_agent


def run_turn(graph, message: str, session_id: str) -> str:
    """Invoke one turn and return the final AI text.

    Retries once on empty output with a nudge. Never recycles a stale
    older AI message — uses a pre-turn message-count snapshot to
    isolate new messages.
    """
    config = {
        "configurable": {"thread_id": session_id},
        "run_name": f"Turn — {session_id[:8]}",
        "tags": [f"session:{session_id}", "sandbox"],
        "metadata": {"session_id": session_id},
    }

    pre_state = graph.get_state(config)
    pre_count = 0
    if pre_state is not None and pre_state.values:
        pre_count = len(pre_state.values.get("messages", []))

    def _invoke_and_extract(input_msgs: list) -> str | None:
        result = graph.invoke({"messages": input_msgs}, config=config)
        all_msgs = result.get("messages", [])
        new_msgs = all_msgs[pre_count:]
        for msg in reversed(new_msgs):
            if not isinstance(msg, AIMessage):
                continue
            c = getattr(msg, "content", "")
            if isinstance(c, list):
                c = " ".join(
                    blk.get("text", "") if isinstance(blk, dict) else str(blk)
                    for blk in c
                )
            if c:
                return c
        return None

    reply = _invoke_and_extract([HumanMessage(content=message)])

    if reply is None:
        logger.warning("Turn produced no AI text — retrying once",
                       extra={"session_id": session_id})
        nudge = HumanMessage(
            content=f"{message}\n\n(Please respond or take the appropriate next action.)"
        )
        mid_state = graph.get_state(config)
        if mid_state is not None and mid_state.values:
            pre_count_retry = len(mid_state.values.get("messages", []))
        else:
            pre_count_retry = pre_count

        def _retry_extract(msgs: list) -> str | None:
            result = graph.invoke({"messages": msgs}, config=config)
            all_msgs = result.get("messages", [])
            new_msgs = all_msgs[pre_count_retry:]
            for msg in reversed(new_msgs):
                if not isinstance(msg, AIMessage):
                    continue
                c = getattr(msg, "content", "")
                if isinstance(c, list):
                    c = " ".join(
                        blk.get("text", "") if isinstance(blk, dict) else str(blk)
                        for blk in c
                    )
                if c:
                    return c
            return None

        reply = _retry_extract([nudge])

    if reply is not None:
        return reply

    logger.warning("Turn produced no AI text after retry",
                   extra={"session_id": session_id})
    return "I wasn't able to produce a response just now. Could you rephrase or try again?"


def get_history(graph, session_id: str) -> list:
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)
    return state.values.get("messages", []) if state else []
