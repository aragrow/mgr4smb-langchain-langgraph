"""GHL Available Slots — retrieves next available calendar slots."""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from mgr4smb.config import settings
from mgr4smb.exceptions import GHLAPIError
from mgr4smb.tools import ghl_client

logger = logging.getLogger(__name__)


def _next_business_day() -> datetime:
    """Return midnight UTC of the next weekday."""
    today = datetime.now(timezone.utc)
    nxt = today + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.replace(hour=0, minute=0, second=0, microsecond=0)


def _get_free_slots_for_day(client, day: datetime) -> list[str]:
    """Fetch free slots for a single calendar day."""
    start_ms = int(day.timestamp() * 1000)
    end_of_day = day.replace(hour=23, minute=59, second=59)
    end_ms = int(end_of_day.timestamp() * 1000)

    params: dict = {
        "startDate": start_ms,
        "endDate": end_ms,
    }
    org_tz = settings.ghl_org_timezone
    if org_tz:
        params["timezone"] = org_tz

    resp = client.get(
        f"/calendars/{settings.ghl_calendar_id}/free-slots",
        params=params,
    )
    resp.raise_for_status()

    data = resp.json()
    date_key = day.strftime("%Y-%m-%d")
    return data.get(date_key, {}).get("slots", [])


def _find_next_available(client, start: datetime, max_days: int = 14) -> tuple[datetime, list[str]]:
    """Walk forward from start, skipping weekends, until slots are found."""
    candidate = start
    for _ in range(max_days):
        slots = _get_free_slots_for_day(client, candidate)
        if slots:
            return candidate, slots
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return start, []


def _format_time(slot_iso: str, user_tz_name: str) -> str:
    """Convert ISO slot time to human-readable in user timezone."""
    try:
        dt = datetime.fromisoformat(slot_iso.replace("Z", "+00:00"))
        tz = ZoneInfo(user_tz_name)
        return dt.astimezone(tz).strftime("%I:%M %p")
    except (ValueError, KeyError):
        return slot_iso


@tool
def ghl_available_slots(contact_identifier: str, user_timezone: str = "") -> str:
    """Retrieve the next available appointment time slots from GoHighLevel.

    Args:
        contact_identifier: Email or phone number of the contact.
        user_timezone: User's timezone for display (e.g. America/New_York). Defaults to org timezone.
    """
    identifier = (contact_identifier or "").strip()
    if not identifier:
        return "Error: A phone number or email address is required."

    user_tz = (user_timezone or "").strip() or settings.ghl_org_timezone
    start_date = _next_business_day()

    try:
        client = ghl_client.get_client()
        contact = ghl_client.search_contact(identifier)
        target_date, slots = _find_next_available(client, start_date)
    except GHLAPIError as e:
        logger.error("ghl_available_slots failed", extra={"tool": "ghl_available_slots", "error": str(e)})
        return f"GHL API error: {e.detail}"

    if contact:
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        contact_name = f"{first} {last}".strip() or identifier
    else:
        contact_name = identifier

    if not slots:
        return (
            f"No available slots found in the next 14 business days for {contact_name}. "
            "The calendar may be fully booked."
        )

    date_label = target_date.strftime("%A, %B %d, %Y")
    top_slots = slots[:5]
    slot_lines = "\n".join(
        f"  {i + 1}. {_format_time(s, user_tz)} ({user_tz}) — slot: {s}"
        for i, s in enumerate(top_slots)
    )
    logger.info("Slots found", extra={"tool": "ghl_available_slots", "count": len(top_slots), "date": date_label})
    return (
        f"Available appointment times for {contact_name} on {date_label}:\n"
        f"{slot_lines}\n"
        "Which slot works best?"
    )
