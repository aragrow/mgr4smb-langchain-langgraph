"""ACCOUNT_AGENT — answers the caller's questions about their own
Jobber records (properties, jobs, visits).

Orchestrator only routes here when the session is already VERIFIED.
The agent uses the caller's email to resolve their Jobber client_id
via jobber_get_clients, then fans out to the relevant read tool.

The system prompt lives in sandbox.prompts.account.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.account import SYSTEM_PROMPT
from sandbox.tools.jobber_get_clients import jobber_get_clients
from sandbox.tools.jobber_get_jobs import jobber_get_jobs
from sandbox.tools.jobber_get_properties import jobber_get_properties
from sandbox.tools.jobber_get_visits import jobber_get_visits


TOOLS = [
    jobber_get_clients,
    jobber_get_properties,
    jobber_get_jobs,
    jobber_get_visits,
]


def build():
    """Return a compiled react agent for ACCOUNT_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
