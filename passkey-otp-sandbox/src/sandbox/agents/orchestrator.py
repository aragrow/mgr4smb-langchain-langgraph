"""ORCHESTRATOR — top-level router for the sandbox.

Responsibilities:
  1. Require the user's email up front.
  2. Greet once per session via greeter_agent (GHL lookup).
  3. Honour session termination (from the authenticator).
  4. Classify intent and delegate:
       - General company question → general_info_agent (knowledge base)
       - Sensitive action         → authenticator_agent (passkey / OTP)
       - Quick conversational     → handled inline
  5. Relay specialist replies verbatim so UI markers (PASSKEY_REQUESTED,
     VERIFIED, UNVERIFIED, CONVERSATION_TERMINATED) reach the browser.

The system prompt lives in sandbox.prompts.orchestrator.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.agents._helpers import agent_as_tool
from sandbox.llm import get_llm
from sandbox.prompts.orchestrator import SYSTEM_PROMPT


def build(greeter_agent, general_info_agent, authenticator_agent):
    """Return a compiled react agent for the sandbox orchestrator.

    All three specialists are passed in pre-built so the wiring is
    explicit in graph.py and there are no circular imports.
    """
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
                "Verify the caller's identity before performing any sensitive "
                "action. Tries a passkey first, falls back to an email OTP. "
                "Pass the user's email in the instruction. Returns replies "
                "that start with VERIFIED, UNVERIFIED, or PASSKEY_REQUESTED."
            ),
        ),
    ]
    return create_react_agent(get_llm(), tools=tools, prompt=SYSTEM_PROMPT)
