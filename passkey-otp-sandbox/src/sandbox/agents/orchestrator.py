"""ORCHESTRATOR — top-level router for the sandbox.

Responsibilities:
  1. Require the user's email up front.
  2. Greet once per session via greeter_agent (GHL lookup).
  3. Honour session termination (from the authenticator).
  4. Classify intent and delegate:
       - General company question → general_info_agent (knowledge base)
       - Own-account query (verified) → account_agent (Jobber records)
       - Sensitive intent (non-account) → authenticator_agent
       - Quick conversational → handled inline
  5. Relay specialist replies verbatim so UI markers (VERIFIED,
     UNVERIFIED, CONVERSATION_TERMINATED) reach the browser.

The system prompt lives in sandbox.prompts.orchestrator.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.agents._helpers import agent_as_tool
from sandbox.llm import get_llm
from sandbox.prompts.orchestrator import SYSTEM_PROMPT
from sandbox.state import AgentState


def build(
    greeter_agent,
    general_info_agent,
    authenticator_agent,
    account_agent,
    appointment_agent,
    service_agent,
):
    """Return a compiled react agent for the sandbox orchestrator."""
    tools = [
        agent_as_tool(
            greeter_agent,
            name="greeter_agent",
            description=(
                "Greet the caller by name if they exist in GoHighLevel, or "
                "with a generic greeting otherwise. Pass the user's email. "
                "Returns a single-line greeting."
            ),
        ),
        agent_as_tool(
            general_info_agent,
            name="general_info_agent",
            description=(
                "Answer general company questions (services, pricing, hours, "
                "location, coverage area, policies, FAQs) by consulting the "
                "knowledge base. Pass the user's question verbatim in the "
                "instruction argument. Does NOT require authentication."
            ),
        ),
        agent_as_tool(
            authenticator_agent,
            name="authenticator_agent",
            description=(
                "Verify the caller's identity via a 6-digit email OTP. "
                "Pass the user's email in the instruction. Returns replies "
                "that start with VERIFIED, UNVERIFIED, or "
                "CONVERSATION_TERMINATED."
            ),
        ),
        agent_as_tool(
            account_agent,
            name="account_agent",
            description=(
                "Answer the caller's own-account questions by reading their "
                "Jobber records (properties, jobs, visits). Pass the caller's "
                "email + their question verbatim in the instruction. The "
                "caller MUST already be VERIFIED this session before this "
                "tool is called."
            ),
        ),
        agent_as_tool(
            appointment_agent,
            name="appointment_agent",
            description=(
                "Full GHL calendar lifecycle: book a NEW appointment, "
                "VIEW existing ones, RESCHEDULE (cancel + rebook), or "
                "CANCEL. Pass the caller's email + their request "
                "verbatim in the instruction. The caller MUST already "
                "be VERIFIED this session."
            ),
        ),
        agent_as_tool(
            service_agent,
            name="service_agent",
            description=(
                "Handle the caller's Jobber service records — properties, "
                "jobs, visits. When they want a change (move a visit, add "
                "instructions), collects Address ID + City, confirms, and "
                "emails the scheduling team + the caller via GHL workflow. "
                "Pass the caller's email + request verbatim. The caller "
                "MUST already be VERIFIED this session."
            ),
        ),
    ]
    # Pass our custom AgentState so is_verified / user_email persist
    # across turns. The default create_react_agent state schema only
    # knows `messages`, so arbitrary custom keys would be dropped on
    # graph.update_state.
    return create_react_agent(
        get_llm(),
        tools=tools,
        prompt=SYSTEM_PROMPT,
        state_schema=AgentState,
    )
