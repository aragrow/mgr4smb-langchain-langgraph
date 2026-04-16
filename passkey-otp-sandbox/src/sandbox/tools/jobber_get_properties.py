"""Jobber Get Properties — lists service addresses for a client.

Also surfaces the caller-facing "Address ID" custom field (configured
via JOBBER_ADDRESS_ID_FIELD_KEY) so the reschedule_agent can match a
caller's stated ID to their property record.
"""

import logging

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import JobberAPIError
from sandbox.tools import jobber_client

logger = logging.getLogger(__name__)


# Includes customFields on each Property so we can surface the
# Address ID (or any other property-level custom field) alongside the
# address. Jobber returns custom fields with both a `label` and a
# `value` dict; we pick the first scalar representation we find.
_QUERY_PROPERTIES = """
query GetProperties($clientId: EncodedId!) {
  client(id: $clientId) {
    id
    firstName
    lastName
    properties {
      id
      address {
        street
        city
        province
        postalCode
        country
      }
      customFields {
        label
        valueText
      }
    }
  }
}
"""


def _format_address(addr: dict) -> str:
    parts = [
        addr.get("street", ""),
        addr.get("city", ""),
        addr.get("province", ""),
        addr.get("postalCode", ""),
        addr.get("country", ""),
    ]
    return ", ".join(p for p in parts if p)


def _address_id(custom_fields: list) -> str:
    """Pull the Address ID out of a Property's customFields list.

    The JOBBER_ADDRESS_ID_FIELD_KEY setting is a dotted key (e.g.
    `property.address_id`); the human-readable label on the field in
    Jobber typically matches the last segment, normalised. We try a
    couple of variants so minor UI-side naming drift doesn't silently
    hide the value.
    """
    want_key = (settings.jobber_address_id_field_key or "").lower()
    want_tail = want_key.rsplit(".", 1)[-1]  # e.g. "address_id"
    candidates = {
        want_tail.replace("_", " ").strip(),        # "address id"
        want_tail.replace("_", "").strip(),         # "addressid"
        want_tail.strip(),                          # "address_id"
        want_key,                                   # full dotted key
    }
    for f in custom_fields or []:
        label = (f.get("label") or "").lower().strip()
        if label in candidates:
            val = f.get("valueText") or ""
            if isinstance(val, str):
                return val.strip()
    return ""


@tool
def jobber_get_properties(client_id_jobber: str) -> str:
    """List the service properties (addresses) for a single Jobber client.

    Each line now includes the caller-facing Address ID pulled from the
    property's custom fields (configured via JOBBER_ADDRESS_ID_FIELD_KEY).

    Args:
        client_id_jobber: Base64-encoded Jobber client ID (from Get Clients).
    """
    cid = (client_id_jobber or "").strip()
    if not cid:
        return "Error: A Jobber client ID is required."

    try:
        data = jobber_client.execute(_QUERY_PROPERTIES, {"clientId": cid})
    except JobberAPIError as e:
        logger.error(
            "jobber_get_properties failed",
            extra={"tool": "jobber_get_properties", "error": str(e)},
        )
        return f"Jobber API error: {e.detail}"

    client = data.get("data", {}).get("client")
    if not client:
        return f"No Jobber client found for ID: {cid}"

    properties_wrapper = client.get("properties", {})
    if isinstance(properties_wrapper, dict):
        properties = properties_wrapper.get("nodes", [])
    else:
        properties = properties_wrapper or []

    name = f"{client.get('firstName', '')} {client.get('lastName', '')}".strip() or cid

    if not properties:
        return f"No properties found for {name} (ID: {cid})."

    lines = [f"Properties ({len(properties)}) for {name}:"]
    for p in properties:
        addr = p.get("address", {}) or {}
        aid = _address_id(p.get("customFields") or [])
        aid_str = f" | Address ID: {aid}" if aid else ""
        lines.append(
            f"- {_format_address(addr)}{aid_str} | Property ID: {p.get('id')}"
        )

    logger.info(
        "Properties returned",
        extra={"tool": "jobber_get_properties", "client_id": cid, "count": len(properties)},
    )
    return "\n".join(lines)
