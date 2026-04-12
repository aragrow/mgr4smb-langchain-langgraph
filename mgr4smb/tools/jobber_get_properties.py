"""Jobber Get Properties — lists service addresses for a client."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_QUERY_PROPERTIES = """
query GetProperties($clientId: EncodedId!) {
  client(id: $clientId) {
    id
    firstName
    lastName
    properties {
      nodes {
        id
        address {
          street
          city
          province
          postalCode
          country
        }
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


@tool
def jobber_get_properties(client_id_jobber: str) -> str:
    """List the service properties (addresses) for a single Jobber client.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID (from Get Clients).
    """
    cid = (client_id_jobber or "").strip()
    if not cid:
        return "Error: A Jobber client ID is required."

    try:
        data = jobber_client.execute(_QUERY_PROPERTIES, {"clientId": cid})
    except JobberAPIError as e:
        logger.error("jobber_get_properties failed", extra={"tool": "jobber_get_properties", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    client = data.get("data", {}).get("client")
    if not client:
        return f"No Jobber client found for ID: {cid}"

    properties_wrapper = client.get("properties", {})
    # Handle both list and paginated shapes
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
        lines.append(f"- {_format_address(addr)} | Property ID: {p.get('id')}")

    logger.info(
        "Properties returned",
        extra={"tool": "jobber_get_properties", "client_id": cid, "count": len(properties)},
    )
    return "\n".join(lines)
