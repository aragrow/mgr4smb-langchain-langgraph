"""GHL Contact Lookup — searches GoHighLevel by email or phone."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import GHLAPIError
from mgr4smb.tools import ghl_client

logger = logging.getLogger(__name__)


@tool
def ghl_contact_lookup(search_value: str) -> str:
    """Look up a contact in GoHighLevel by email or phone number.

    Returns the contact's name and ID if found, or a not-found message.
    """
    identifier = (search_value or "").strip()
    if not identifier:
        return "Error: An email address or phone number is required."

    try:
        contact = ghl_client.search_contact(identifier)
    except GHLAPIError as e:
        logger.error("ghl_contact_lookup failed", extra={"tool": "ghl_contact_lookup", "error": str(e)})
        return f"GHL API error: {e.detail}"

    if not contact:
        return f"No contact found in GoHighLevel for: {identifier}"

    first = contact.get("firstName", "")
    last = contact.get("lastName", "")
    contact_name = f"{first} {last}".strip() or identifier
    contact_id = contact.get("id", "")

    logger.info("Contact found", extra={"tool": "ghl_contact_lookup", "contact_id": contact_id})
    return f"Contact found: {contact_name} (ID: {contact_id})"
