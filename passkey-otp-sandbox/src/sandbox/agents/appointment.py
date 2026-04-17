"""APPOINTMENT_AGENT — full GHL calendar lifecycle.

Replaces the former booking_agent. Handles: book NEW appointments,
VIEW existing, RESCHEDULE (cancel + rebook), and CANCEL. After
creating an appointment, GHL's own automation sends the confirmation
email/SMS to the contact.

The system prompt lives in sandbox.prompts.appointment.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.appointment import SYSTEM_PROMPT
from sandbox.tools.ghl_available_slots import ghl_available_slots
from sandbox.tools.ghl_book_appointment import ghl_book_appointment
from sandbox.tools.ghl_cancel_appointment import ghl_cancel_appointment
from sandbox.tools.ghl_get_appointments import ghl_get_appointments


TOOLS = [
    ghl_available_slots,
    ghl_book_appointment,
    ghl_get_appointments,
    ghl_cancel_appointment,
]


def build():
    """Return a compiled react agent for APPOINTMENT_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
