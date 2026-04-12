"""GHL Get Appointments — retrieves upcoming appointments for a contact."""

import logging
from datetime import datetime, timedelta, timezone
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
def ghl_get_appointments(contact_identifier: str, user_timezone: str = "") -> str:
    """Retrieve upcoming booked appointments for a contact from GoHighLevel.

    Args:
        contact_identifier: Email or phone to identify the contact.
        user_timezone: User's timezone for display. Defaults to org timezone.
    """
    identifier = (contact_identifier or "").strip()
    if not identifier:
        return "Error: A phone number or email address is required."

    user_tz = (user_timezone or "").strip() or settings.ghl_org_timezone

    try:
        contact = ghl_client.search_contact(identifier)
        if not contact:
            return f"No contact found for '{identifier}'."

        contact_id = contact["id"]
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        contact_name = f"{first} {last}".strip() or identifier

        client = ghl_client.get_client()

        # Fetch appointments for the next 90 days
        now = datetime.now(timezone.utc)
        end_range = now + timedelta(days=90)

        resp = client.get(
            f"/contacts/{contact_id}/appointments",
            params={
                "startDate": int(now.timestamp() * 1000),
                "endDate": int(end_range.timestamp() * 1000),
            },
        )
        resp.raise_for_status()
        data = resp.json()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("ghl_get_appointments failed", extra={"tool": "ghl_get_appointments"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    # Filter to active appointments (not cancelled)
    events = data.get("events", data.get("appointments", []))
    active = [
        ev for ev in events
        if ev.get("appointmentStatus", ev.get("status", "")).lower()
        in ("confirmed", "new", "showed")
    ]

    # Sort by start time
    active.sort(key=lambda ev: ev.get("startTime", ev.get("start", "")))

    if not active:
        return f"No upcoming appointments found for {contact_name}."

    lines = []
    for i, ev in enumerate(active, 1):
        start = ev.get("startTime", ev.get("start", ""))
        title = ev.get("title", ev.get("name", "Appointment"))
        status = ev.get("appointmentStatus", ev.get("status", ""))
        event_id = ev.get("id", "")
        time_str = _format_time(start, user_tz)
        lines.append(f"  {i}. {title} — {time_str} ({status}) [EVENT_ID: {event_id}]")

    logger.info(
        "Appointments retrieved",
        extra={"tool": "ghl_get_appointments", "contact_id": contact_id, "count": len(active)},
    )
    return f"Upcoming appointments for {contact_name}:\n" + "\n".join(lines)
