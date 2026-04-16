"""RESCHEDULE_AGENT — handles reschedule requests for VERIFIED callers.

Collects Address ID + City (to identify the property), the current
job/visit, and the proposed new time. Asks for explicit confirmation.
Hands off to vendor_notifier_agent which emails the scheduling team
via the GHL workflow pipeline.

Orchestrator only routes here AFTER the caller has been verified
this session. The agent does not touch identity itself.

The system prompt lives in sandbox.prompts.reschedule.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.agents._helpers import agent_as_tool
from sandbox.llm import get_llm
from sandbox.prompts.reschedule import SYSTEM_PROMPT
from sandbox.tools.jobber_get_clients import jobber_get_clients
from sandbox.tools.jobber_get_properties import jobber_get_properties
from sandbox.tools.jobber_get_visits import jobber_get_visits


def build(vendor_notifier_agent, client_notifier_agent):
    """Return a compiled react agent for RESCHEDULE_AGENT.

    Args:
        vendor_notifier_agent: Compiled VENDOR_NOTIFIER_AGENT. Called
            once after the caller confirms the reschedule details to
            email the scheduling team.
        client_notifier_agent: Compiled CLIENT_NOTIFIER_AGENT. Called
            once AFTER the vendor notification succeeds, to give the
            caller an email copy of what was sent to the team.
    """
    tools = [
        jobber_get_clients,
        jobber_get_properties,
        jobber_get_visits,
        agent_as_tool(
            vendor_notifier_agent,
            name="vendor_notifier_agent",
            description=(
                "Internal agent that composes and dispatches the reschedule "
                "email to the scheduling team via the GHL workflow. Call "
                "EXACTLY ONCE per request, after the caller has confirmed. "
                "Pass a structured instruction with contact_email, "
                "caller_name, property_address, job_title, "
                "current_visit_start, proposed_new_time, and optional "
                "extra_notes. Returns a reply starting with RESCHEDULE_SENT "
                "or RESCHEDULE_FAILED."
            ),
        ),
        agent_as_tool(
            client_notifier_agent,
            name="client_notifier_agent",
            description=(
                "Internal agent that emails the CALLER a confirmation "
                "via the GHL client-notification workflow. Call EXACTLY "
                "ONCE after vendor_notifier_agent returns RESCHEDULE_SENT, "
                "to give the caller an email trail. Pass an instruction "
                "with contact_email, caller_name, reason="
                "'reschedule_confirmation', and a context field that "
                "echoes the job, address, current time, and proposed "
                "time. Returns a reply starting with CLIENT_NOTIFIED or "
                "CLIENT_NOTIFICATION_FAILED."
            ),
        ),
    ]
    return create_react_agent(get_llm(), tools=tools, prompt=SYSTEM_PROMPT)
