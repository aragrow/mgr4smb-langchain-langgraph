"""Jobber Create Client — creates a new client via GraphQL mutation."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_MUTATION_CREATE_CLIENT = """
mutation CreateClient($input: ClientCreateInput!) {
  clientCreate(input: $input) {
    client {
      id
      firstName
      lastName
      companyName
      emails { address primary }
      phones { number primary }
    }
    userErrors { message path }
  }
}
"""


@tool
def jobber_create_client(
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    company_name: str = "",
) -> str:
    """Create a new client in Jobber.

    Use this when jobber_get_clients returns no match for the user's email/phone
    and you need to create the client before creating a property or job.

    Args:
        first_name: Client's first name.
        last_name: Client's last name.
        email: Primary email address.
        phone: Primary phone number.
        company_name: Optional company name.
    """
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    em = (email or "").strip()
    ph = (phone or "").strip()

    if not fn or not ln:
        return "Error: First name and last name are required."
    if not em and not ph:
        return "Error: At least one of email or phone is required."

    input_obj: dict = {
        "firstName": fn,
        "lastName": ln,
    }
    if company_name.strip():
        input_obj["companyName"] = company_name.strip()
    if em:
        input_obj["emails"] = [{"address": em, "primary": True, "description": "MAIN"}]
    if ph:
        input_obj["phones"] = [{"number": ph, "primary": True, "description": "MAIN"}]

    try:
        data = jobber_client.execute(_MUTATION_CREATE_CLIENT, {"input": input_obj})
    except JobberAPIError as e:
        logger.error("jobber_create_client failed", extra={"tool": "jobber_create_client", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    result = data.get("data", {}).get("clientCreate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        detail = "; ".join(f"{e.get('path', '')}: {e.get('message', '')}" for e in user_errors)
        return f"Could not create client: {detail}"

    client = result.get("client")
    if not client:
        return "Client creation returned no data."

    client_id = client.get("id")
    full_name = f"{client.get('firstName', '')} {client.get('lastName', '')}".strip()
    logger.info(
        "Client created",
        extra={"tool": "jobber_create_client", "client_id": client_id, "name": full_name},
    )
    return f"Client created: {full_name} (ID: {client_id})"
