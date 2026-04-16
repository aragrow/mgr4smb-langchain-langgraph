"""GREETING_AGENT — welcomes the caller by name (or generically).

Ported from mgr4smb/agents/greeting.py. Looks up the caller in
GoHighLevel by email and emits a one-line greeting.

The system prompt lives in sandbox.prompts.greeting.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.greeting import SYSTEM_PROMPT
from sandbox.tools.ghl_contact_lookup import ghl_contact_lookup


TOOLS = [ghl_contact_lookup]


def build():
    """Return a compiled react agent for GREETING_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
