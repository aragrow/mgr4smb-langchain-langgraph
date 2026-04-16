"""Shared GoHighLevel HTTP client — connection pooling, auth, timeouts.

Ported from mgr4smb/tools/ghl_client.py. All GHL tools in the sandbox
use this singleton instead of creating their own httpx sessions.
"""

import logging

import httpx

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError

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
    """Search GHL contacts by email or phone. Returns first match or None."""
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


def fetch_contact(contact_id: str) -> dict:
    """GET /contacts/{id} — returns the canonical, fresh contact record.

    Use this whenever you need up-to-date custom field values. The
    /contacts/search endpoint returns custom-field values from a search
    index that lags behind PUTs by several seconds, which breaks OTP
    verification (we'd never see the freshly-written code).
    """
    try:
        resp = get_client().get(f"/contacts/{contact_id}")
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "GHL fetch_contact failed",
            extra={"status": e.response.status_code, "body": e.response.text[:200]},
        )
        raise GHLAPIError(e.response.status_code, e.response.text[:200]) from e
    except httpx.ConnectError as e:
        logger.error("GHL unreachable on fetch_contact", extra={"error": str(e)})
        raise GHLAPIError(503, "Service unreachable") from e

    data = resp.json()
    return data.get("contact", data)


# ---------------------------------------------------------------------------
# Custom field key → id resolver
# ---------------------------------------------------------------------------
# GHL's contact custom-fields API requires the field's UUID id, NOT the
# human-readable key like "contact.otp_code". Calls that pass the key
# silently succeed (200 OK) without writing anything. Likewise, GET on a
# contact returns customFields with id populated but key=None, so reads
# must also go through the id.

_FIELD_ID_CACHE: dict[str, str] = {}


def resolve_custom_field_id(key_or_id: str) -> str:
    """Map a human-readable custom field key to the GHL field UUID.

    Accepts either:
      - 'contact.otp_code' or just 'otp_code' (will be looked up)
      - A raw field id (returned as-is — no lookup)

    Caches the resolution per process. Raises GHLAPIError if the key is
    not found in the location's custom-fields catalogue.
    """
    if key_or_id in _FIELD_ID_CACHE:
        return _FIELD_ID_CACHE[key_or_id]

    # Heuristic: raw GHL ids contain no dot and are alphanumeric (~20 chars).
    if "." not in key_or_id and len(key_or_id) >= 15 and key_or_id.isalnum():
        _FIELD_ID_CACHE[key_or_id] = key_or_id
        return key_or_id

    try:
        resp = get_client().get(
            f"/locations/{settings.ghl_location_id}/customFields"
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            "GHL custom-fields fetch failed",
            extra={"status": e.response.status_code, "body": e.response.text[:200]},
        )
        raise GHLAPIError(e.response.status_code, e.response.text[:200]) from e

    definitions = resp.json().get("customFields", [])
    want = key_or_id if key_or_id.startswith("contact.") else f"contact.{key_or_id}"

    for d in definitions:
        if d.get("fieldKey") in (want, key_or_id) or d.get("name") == key_or_id:
            field_id = d["id"]
            _FIELD_ID_CACHE[key_or_id] = field_id
            logger.info(
                "Resolved GHL custom field",
                extra={"key": key_or_id, "field_id": field_id[:8] + "..."},
            )
            return field_id

    raise GHLAPIError(
        404,
        f"Custom field '{key_or_id}' not found in GHL location "
        f"{settings.ghl_location_id}. Create it under Settings > Custom Fields.",
    )
