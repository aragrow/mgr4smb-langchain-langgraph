"""GHL Available Slots — list the next available calendar slots.

Ported from mgr4smb/tools/ghl_available_slots.py and enhanced:
  - Returns the first 2 open days (not just the first one).
  - Accepts an optional `preferred_start_date` so the caller can
    target a specific date (e.g. "next Wednesday").
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


def _next_business_day() -> datetime:
    today = datetime.now(timezone.utc)
    nxt = today + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.replace(hour=0, minute=0, second=0, microsecond=0)


def _get_free_slots_for_day(client, day: datetime) -> list[str]:
    start_ms = int(day.timestamp() * 1000)
    end_of_day = day.replace(hour=23, minute=59, second=59)
    end_ms = int(end_of_day.timestamp() * 1000)

    params: dict = {"startDate": start_ms, "endDate": end_ms}
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


def _find_next_n_available(
    client, start: datetime, n: int = 2, max_days: int = 14,
) -> list[tuple[datetime, list[str]]]:
    """Walk forward from `start`, skip weekends, collect up to `n` days
    that have at least one open slot. Caps at `max_days` total days
    scanned to avoid runaway API calls on a mostly-full calendar.
    """
    results: list[tuple[datetime, list[str]]] = []
    candidate = start
    scanned = 0
    while len(results) < n and scanned < max_days:
        slots = _get_free_slots_for_day(client, candidate)
        if slots:
            results.append((candidate, slots))
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        scanned += 1
    return results


def _format_time(slot_iso: str, user_tz_name: str) -> str:
    try:
        dt = datetime.fromisoformat(slot_iso.replace("Z", "+00:00"))
        tz = ZoneInfo(user_tz_name)
        return dt.astimezone(tz).strftime("%I:%M %p")
    except (ValueError, KeyError):
        return slot_iso


def _parse_date(s: str) -> datetime | None:
    """Best-effort parse of an ISO-ish date string into a midnight UTC datetime."""
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return None


@tool
def ghl_available_slots(
    contact_identifier: str,
    user_timezone: str = "",
    preferred_start_date: str = "",
) -> str:
    """Retrieve the next available appointment time slots from GoHighLevel.

    Returns slots for up to 2 open days so the caller has choices.
    Each day shows up to 5 slots.

    Args:
        contact_identifier: Email or phone of the caller.
        user_timezone: User's timezone for display (e.g. America/New_York).
            Defaults to the org timezone.
        preferred_start_date: Optional ISO date (e.g. "2026-04-22") to
            start searching from. If blank, defaults to the next
            business day. Use this when the caller asks for a specific
            date — the tool will return up to 2 open days starting
            from that date (or after, if that date is full).
    """
    identifier = (contact_identifier or "").strip()
    if not identifier:
        return "Error: A phone number or email address is required."

    user_tz = (user_timezone or "").strip() or settings.ghl_org_timezone

    start_date = _parse_date(preferred_start_date) or _next_business_day()
    # Don't search in the past.
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if start_date < now:
        start_date = _next_business_day()

    try:
        client = ghl_client.get_client()
        contact = ghl_client.search_contact(identifier)
        open_days = _find_next_n_available(client, start_date, n=2)
    except GHLAPIError as e:
        logger.error(
            "ghl_available_slots failed",
            extra={"tool": "ghl_available_slots", "error": str(e)},
        )
        return f"GHL API error: {e.detail}"

    if contact:
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        contact_name = f"{first} {last}".strip() or identifier
    else:
        contact_name = identifier

    if not open_days:
        return (
            f"No available slots found in the next 14 business days "
            f"(starting {start_date.strftime('%Y-%m-%d')}) for "
            f"{contact_name}. The calendar may be fully booked."
        )

    lines = [f"Available appointment times for {contact_name}:"]
    slot_num = 0
    for day, slots in open_days:
        date_label = day.strftime("%A, %B %d, %Y")
        lines.append(f"\n  {date_label}:")
        for s in slots[:5]:
            slot_num += 1
            lines.append(
                f"    {slot_num}. {_format_time(s, user_tz)} ({user_tz}) — slot: {s}"
            )

    total = sum(min(len(s), 5) for _, s in open_days)
    logger.info(
        "Slots found",
        extra={
            "tool": "ghl_available_slots",
            "open_days": len(open_days),
            "total_slots": total,
        },
    )
    lines.append("\nWhich slot works best?")
    return "\n".join(lines)
