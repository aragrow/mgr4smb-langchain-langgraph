"""CLIENT_NOTIFIER_AGENT — internal agent that emails the caller via GHL.

Mirror of vendor_notifier_agent, but the recipient is the caller
(client) rather than the scheduling team. Invoked by peer agents
(e.g. reschedule_agent) when they need to send the caller a
confirmation or status email OUT-OF-BAND (separate from the chat
reply).

The system prompt lives in sandbox.prompts.client_notifier.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.client_notifier import SYSTEM_PROMPT
from sandbox.tools.send_client_notification import send_client_notification


TOOLS = [send_client_notification]


def build():
    """Return a compiled react agent for CLIENT_NOTIFIER_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
