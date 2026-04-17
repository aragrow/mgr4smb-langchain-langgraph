"""GHL Cancel Appointment — cancels an existing appointment by event ID.

Ported from mgr4smb/tools/ghl_cancel_appointment.py. Verifies
ownership (contactId matches) before marking as cancelled. GHL
preserves the record; it's not deleted.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


def _format_time(iso_str: str, user_tz_name: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(user_tz_name)).strftime("%I:%M %p on %A, %B %d, %Y")
    except (ValueError, KeyError):
        return iso_str


@tool
def ghl_cancel_appointment(
    event_id: str,
    contact_identifier: str,
    user_timezone: str = "",
) -> str:
    """Cancel an existing appointment in GoHighLevel by event ID.

    Verifies that the appointment belongs to the contact before cancelling.

    Args:
        event_id: The GHL event/appointment ID to cancel.
        contact_identifier: Email or phone for ownership verification.
        user_timezone: User's timezone for the confirmation message.
    """
    eid = (event_id or "").strip()
    identifier = (contact_identifier or "").strip()

    if not eid:
        return "Error: An event ID is required."
    if not identifier:
        return "Error: A contact email or phone is required for verification."

    user_tz = (user_timezone or "").strip() or settings.ghl_org_timezone

    try:
        contact = ghl_client.search_contact(identifier)
        if not contact:
            return f"No contact found for '{identifier}'."

        contact_id = contact["id"]
        client = ghl_client.get_client()

        resp = client.get(f"/calendars/events/appointments/{eid}")
        resp.raise_for_status()
        event = resp.json()

        event_contact_id = event.get("contactId", event.get("contact", {}).get("id", ""))
        if event_contact_id != contact_id:
            return "This appointment does not belong to your account."

        title = event.get("title", "Appointment")
        start = event.get("startTime", event.get("start", ""))

        resp = client.put(
            f"/calendars/events/appointments/{eid}",
            json={"appointmentStatus": "cancelled"},
        )
        resp.raise_for_status()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("ghl_cancel_appointment failed", extra={"tool": "ghl_cancel_appointment"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    time_str = _format_time(start, user_tz)
    logger.info(
        "Appointment cancelled",
        extra={"tool": "ghl_cancel_appointment", "event_id": eid, "contact_id": contact_id},
    )
    return f"Appointment cancelled: {title} at {time_str} (Event ID: {eid})"
