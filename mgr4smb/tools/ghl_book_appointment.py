"""GHL Book Appointment — books a confirmed appointment in GoHighLevel."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from mgr4smb.config import settings
from mgr4smb.exceptions import GHLAPIError
from mgr4smb.tools import ghl_client

logger = logging.getLogger(__name__)


def _format_time(iso_str: str, user_tz_name: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(user_tz_name)).strftime("%I:%M %p on %A, %B %d, %Y")
    except (ValueError, KeyError):
        return iso_str


@tool
def ghl_book_appointment(
    contact_identifier: str,
    selected_slot: str,
    service_name: str,
    user_timezone: str = "",
) -> str:
    """Book a confirmed appointment in GoHighLevel.

    Args:
        contact_identifier: Email or phone to identify the contact.
        selected_slot: ISO 8601 slot time from Available Slots (e.g. 2026-04-03T10:00:00-04:00).
        service_name: Appointment title / service name.
        user_timezone: User's timezone for the confirmation message. Defaults to org timezone.
    """
    identifier = (contact_identifier or "").strip()
    slot = (selected_slot or "").strip()
    service = (service_name or "").strip()

    if not identifier:
        return "Error: A phone number or email address is required."
    if not slot:
        return "Error: No slot was selected. Please choose a time slot first."
    if not service:
        return "Error: A service name is required."

    user_tz = (user_timezone or "").strip() or settings.ghl_org_timezone
    duration = settings.ghl_slot_duration_minutes

    try:
        start_dt = datetime.fromisoformat(slot.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=duration)
    except (ValueError, AttributeError):
        return f"Error: Could not parse the selected slot time '{slot}'. Expected ISO format."

    try:
        client = ghl_client.get_client()
        contact = ghl_client.search_contact(identifier)

        if not contact:
            return f"Could not find a contact matching '{identifier}'. Please verify the email or phone number."

        contact_id = contact["id"]
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        contact_name = f"{first} {last}".strip() or identifier

        appointment_body = {
            "calendarId": settings.ghl_calendar_id,
            "locationId": settings.ghl_location_id,
            "contactId": contact_id,
            "startTime": start_dt.isoformat(),
            "endTime": end_dt.isoformat(),
            "title": service,
            "appointmentStatus": "confirmed",
        }

        resp = client.post("/calendars/events/appointments", json=appointment_body)
        resp.raise_for_status()
        result = resp.json()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("ghl_book_appointment failed", extra={"tool": "ghl_book_appointment"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    event_id = result.get("id", "unknown")
    time_display = _format_time(start_dt.isoformat(), user_tz)

    logger.info(
        "Appointment booked",
        extra={"tool": "ghl_book_appointment", "event_id": event_id, "contact_id": contact_id},
    )
    return (
        f"Appointment confirmed for {contact_name}!\n"
        f"  Service: {service}\n"
        f"  Time: {time_display}\n"
        f"  Confirmation ID: {event_id}"
    )
