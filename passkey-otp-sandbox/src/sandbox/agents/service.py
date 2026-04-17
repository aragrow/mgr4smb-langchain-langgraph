"""SERVICE_AGENT — handles the caller's Jobber service records.

Replaces the former reschedule_agent. Reads properties, jobs, and
visits from Jobber; when the caller wants a change (move a visit,
update instructions, etc.), collects the details, confirms, then
delegates to vendor_notifier + client_notifier to email the
scheduling team and the caller.

Does NOT touch GHL calendar appointments — that's appointment_agent.

The system prompt lives in sandbox.prompts.service.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.agents._helpers import agent_as_tool
from sandbox.llm import get_llm
from sandbox.prompts.service import SYSTEM_PROMPT
from sandbox.tools.jobber_get_clients import jobber_get_clients
from sandbox.tools.jobber_get_properties import jobber_get_properties
from sandbox.tools.jobber_get_visits import jobber_get_visits


def build(vendor_notifier_agent, client_notifier_agent):
    """Return a compiled react agent for SERVICE_AGENT."""
    tools = [
        jobber_get_clients,
        jobber_get_properties,
        jobber_get_visits,
        agent_as_tool(
            vendor_notifier_agent,
            name="vendor_notifier_agent",
            description=(
                "Internal agent that composes and dispatches a service-change "
                "request email to the scheduling team via GHL. Call EXACTLY "
                "ONCE per request, after the caller has confirmed. Pass a "
                "structured instruction with contact_email, caller_name, "
                "property_address, job_title, current_visit_start, "
                "proposed_new_time, assigned_vendor, and optional extra_notes. "
                "Returns RESCHEDULE_SENT or RESCHEDULE_FAILED."
            ),
        ),
        agent_as_tool(
            client_notifier_agent,
            name="client_notifier_agent",
            description=(
                "Internal agent that emails the CALLER a confirmation copy "
                "via the GHL client-notification workflow. Call EXACTLY ONCE "
                "after vendor_notifier returns RESCHEDULE_SENT. Pass "
                "contact_email, caller_name, reason='reschedule_confirmation', "
                "and a context field echoing the job, address, current time, "
                "and proposed time. Returns CLIENT_NOTIFIED or "
                "CLIENT_NOTIFICATION_FAILED."
            ),
        ),
    ]
    return create_react_agent(get_llm(), tools=tools, prompt=SYSTEM_PROMPT)
