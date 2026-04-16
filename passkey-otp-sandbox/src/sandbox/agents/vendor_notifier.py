"""VENDOR_NOTIFIER_AGENT — internal agent that emails the vendor via GHL.

Invoked only by the reschedule_agent with a structured payload.
Composes a short courteous email, fires
send_vendor_reschedule_request exactly once, returns a status string.

The system prompt lives in sandbox.prompts.vendor_notifier.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.vendor_notifier import SYSTEM_PROMPT
from sandbox.tools.send_vendor_reschedule_request import send_vendor_reschedule_request


TOOLS = [send_vendor_reschedule_request]


def build():
    """Return a compiled react agent for VENDOR_NOTIFIER_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
