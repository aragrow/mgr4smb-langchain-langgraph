"""Shared GoHighLevel HTTP client — connection pooling, auth, timeouts.

All GHL tools use this client instead of creating their own httpx sessions.
"""

import logging

import httpx

from mgr4smb.config import settings
from mgr4smb.exceptions import GHLAPIError

logger = logging.getLogger(__name__)

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    """Return a singleton httpx.Client with GHL auth headers and timeouts."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.Client(
            base_url=GHL_BASE,
            headers={
                "Authorization": f"Bearer {settings.ghl_api_key}",
                "Content-Type": "application/json",
                "Version": GHL_VERSION,
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        logger.info("GHL httpx.Client initialised base_url=%s", GHL_BASE)
    return _client


def search_contact(email_or_phone: str) -> dict | None:
    """Search GHL contacts by email or phone. Returns first match or None.

    Raises GHLAPIError on HTTP errors.
    """
    identifier = email_or_phone.strip().lower()
    if not identifier:
        return None

    search_field = "email" if "@" in identifier else "phone"

    body = {
        "locationId": settings.ghl_location_id,
        "pageLimit": 1,
        "filters": [
            {
                "group": "AND",
                "filters": [
                    {
                        "field": search_field,
                        "operator": "eq",
                        "value": identifier,
                    }
                ],
            }
        ],
    }

    try:
        resp = get_client().post("/contacts/search", json=body)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "GHL contact search failed",
            extra={"status": e.response.status_code, "body": e.response.text[:200]},
        )
        raise GHLAPIError(e.response.status_code, e.response.text[:200]) from e
    except httpx.ConnectError as e:
        logger.error("GHL unreachable during contact search", extra={"error": str(e)})
        raise GHLAPIError(503, "Service unreachable") from e

    contacts = resp.json().get("contacts", [])
    if contacts:
        logger.debug("GHL contact found id=%s", contacts[0].get("id"))
    return contacts[0] if contacts else None


def require_contact(email_or_phone: str, contact_id: str | None = None) -> dict:
    """Return a contact dict — uses cached contact_id if provided, else searches.

    Raises GHLAPIError if not found.
    """
    if contact_id:
        return {"id": contact_id}

    contact = search_contact(email_or_phone)
    if not contact:
        raise GHLAPIError(404, f"No contact found for '{email_or_phone}'")
    return contact
