"""Jobber Get Clients — searches clients by name, email, phone, or Jobber ID."""

import logging
import re

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_QUERY_BY_ID = """
query GetClientById($id: EncodedId!) {
  client(id: $id) {
    id
    firstName
    lastName
    companyName
    emails { address description primary }
    phones { number description primary }
  }
}
"""

_QUERY_ALL = """
query GetClients($cursor: String) {
  clients(after: $cursor, first: 50) {
    nodes {
      id
      firstName
      lastName
      companyName
      emails { address description primary }
      phones { number description primary }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _detect_search_type(value: str) -> str:
    """Infer filter type from value format: email, phone, id, or name."""
    value = value.strip()
    if "@" in value:
        return "email"
    if re.match(r"^\+?[\d\s\-().]{7,15}$", value):
        return "phone"
    if re.match(r"^[A-Za-z0-9+/=]{12,}$", value) and " " not in value:
        return "id"
    return "name"


def _filter_clients(clients: list, search: str, search_type: str) -> list:
    search = search.lower()
    results = []
    for c in clients:
        if search_type == "email":
            match = any(search in e["address"].lower() for e in c.get("emails", []))
        elif search_type == "phone":
            digits = re.sub(r"\D", "", search)
            match = any(digits in re.sub(r"\D", "", p["number"]) for p in c.get("phones", []))
        else:  # name / company
            full_name = f"{c.get('firstName', '')} {c.get('lastName', '')}".lower()
            company = (c.get("companyName") or "").lower()
            match = search in full_name or search in company
        if match:
            results.append(c)
    return results


def _format_client_line(c: dict) -> str:
    name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
    company = c.get("companyName") or ""
    primary_email = next((e["address"] for e in c.get("emails", []) if e.get("primary")), "")
    primary_phone = next((p["number"] for p in c.get("phones", []) if p.get("primary")), "")
    return (
        f"- {name}{' | ' + company if company else ''}"
        f" | {primary_email} | {primary_phone} | ID: {c['id']}"
    )


@tool
def jobber_get_clients(search_value: str = "") -> str:
    """Search Jobber clients by name, email, phone, or Jobber client ID.

    Auto-detects the filter type based on format:
      - '@' → email substring match
      - digits → phone (digit-only comparison)
      - base64-like → direct ID lookup (fastest)
      - anything else → name or company substring match

    Leave blank to return up to 50 clients (no filter).
    """
    search = (search_value or "").strip()
    search_type = _detect_search_type(search) if search else "none"

    try:
        if search_type == "id":
            data = jobber_client.execute(_QUERY_BY_ID, {"id": search})
            contact = data.get("data", {}).get("client")
            clients = [contact] if contact else []
        else:
            data = jobber_client.execute(_QUERY_ALL, {"cursor": None})
            all_clients = data.get("data", {}).get("clients", {}).get("nodes", [])
            clients = _filter_clients(all_clients, search, search_type) if search else all_clients
    except JobberAPIError as e:
        logger.error("jobber_get_clients failed", extra={"tool": "jobber_get_clients", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    if not clients:
        label = f" ({search_type}: '{search}')" if search else ""
        return f"No clients found{label}."

    lines = [f"Clients ({len(clients)}) — filter: {search_type}:"]
    lines.extend(_format_client_line(c) for c in clients)
    logger.info(
        "Clients returned",
        extra={"tool": "jobber_get_clients", "count": len(clients), "search_type": search_type},
    )
    return "\n".join(lines)
