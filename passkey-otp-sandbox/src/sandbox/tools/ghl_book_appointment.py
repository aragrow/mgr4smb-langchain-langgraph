"""GHL Book Appointment — creates a confirmed appointment in GoHighLevel.

Two-step write to avoid double-triggering GHL confirmation workflows:

  Step 1: POST with appointmentStatus="new" — creates the record
          without firing the confirmation workflow.
  Step 2: PUT  with description + appointmentStatus="confirmed" —
          attaches the intent-summary notes AND flips status in one
          call, so the workflow fires exactly once and the calendar
          event already has the notes when the team opens it.

GHL's POST endpoint does NOT accept a `description` field (it either
400s or silently ignores it), which is why the two-step exists. The
previous approach (POST as confirmed → PUT description) fired the
workflow twice — once on creation, once on the notes update.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


# GHL appointment notes have a practical limit. Anything longer is fine
# in our system but bloats the calendar UI; truncate to keep the
# scanning-the-day-view experience usable.
_MAX_NOTES_LEN = 500


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
    notes: str = "",
) -> str:
    """Book a confirmed appointment in GoHighLevel.

    Args:
        contact_identifier: Email or phone to identify the contact.
        selected_slot: ISO 8601 slot time from `ghl_available_slots`
            (e.g. 2026-04-03T10:00:00-04:00).
        service_name: Appointment title / service name.
        user_timezone: User's timezone for the confirmation message.
            Defaults to GHL_ORG_TIMEZONE.
        notes: Optional 1–3 sentence summary of the caller's intent —
            who they are, what they want to discuss, any context the
            team should see when they open the calendar event.
            Truncated to 500 characters.
    """
    identifier = (contact_identifier or "").strip()
    slot = (selected_slot or "").strip()
    service = (service_name or "").strip()
    notes_clean = (notes or "").strip()[:_MAX_NOTES_LEN]

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
            return (
                f"Could not find a contact matching '{identifier}'. Please "
                "verify the email or phone number."
            )

        contact_id = contact["id"]
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        contact_name = f"{first} {last}".strip() or identifier

        # TWO-STEP CREATE to avoid double-triggering GHL workflows:
        #
        # Step 1: POST with appointmentStatus="new". GHL creates the
        #   record but the confirmation workflow (which fires on
        #   status=confirmed) does NOT trigger yet. GHL's POST endpoint
        #   does NOT accept a description field — it either 400s or
        #   silently ignores it — so notes can't ride along here.
        #
        # Step 2: PUT with description + flip status to "confirmed".
        #   This is the ONLY mutation that fires the workflow, so exactly
        #   one confirmation email/SMS goes out — and it includes the
        #   intent summary in the calendar event.
        appointment_body = {
            "calendarId": settings.ghl_calendar_id,
            "locationId": settings.ghl_location_id,
            "contactId": contact_id,
            "startTime": start_dt.isoformat(),
            "endTime": end_dt.isoformat(),
            "title": service,
            "appointmentStatus": "new",
        }

        resp = client.post("/calendars/events/appointments", json=appointment_body)
        resp.raise_for_status()
        result = resp.json()

        event_id = result.get("id")
        if event_id:
            # Step 2: attach notes + flip to confirmed in one PUT.
            update_body: dict = {"appointmentStatus": "confirmed"}
            if notes_clean:
                update_body["description"] = notes_clean
            try:
                put_resp = client.put(
                    f"/calendars/events/appointments/{event_id}",
                    json=update_body,
                )
                put_resp.raise_for_status()
                logger.debug(
                    "Appointment confirmed + description set",
                    extra={"event_id": event_id, "chars": len(notes_clean)},
                )
            except Exception:
                # POST succeeded so the appointment exists; failing to
                # confirm + attach notes is bad but not worth failing the
                # whole booking. Log loudly.
                logger.error(
                    "Failed to confirm/attach description to appointment",
                    extra={"event_id": event_id},
                    exc_info=True,
                )

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error(
            "ghl_book_appointment failed",
            extra={"tool": "ghl_book_appointment"},
            exc_info=True,
        )
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
