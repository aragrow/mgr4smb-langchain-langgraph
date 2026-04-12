"""Jobber Create Property — creates a service property for a client."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_MUTATION_CREATE_PROPERTY = """
mutation CreateProperty($input: PropertyCreateInput!) {
  propertyCreate(input: $input) {
    property {
      id
      address {
        street
        city
        province
        postalCode
        country
      }
    }
    userErrors { message path }
  }
}
"""


@tool
def jobber_create_property(
    client_id_jobber: str,
    street: str,
    city: str,
    province: str = "",
    postal_code: str = "",
    country: str = "",
    property_type: str = "",
    bedrooms: int = 0,
    bathrooms: int = 0,
    offices: int = 0,
) -> str:
    """Create a service property for a Jobber client.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID.
        street: Street address.
        city: City.
        province: State or province.
        postal_code: ZIP or postal code.
        country: Country.
        property_type: "house", "apartment", or "office" (stored in notes).
        bedrooms: Number of bedrooms (for house/apartment).
        bathrooms: Number of bathrooms.
        offices: Number of offices (for office type).
    """
    cid = (client_id_jobber or "").strip()
    st = (street or "").strip()
    ct = (city or "").strip()

    if not cid:
        return "Error: A Jobber client ID is required."
    if not st or not ct:
        return "Error: Street and city are required."

    address: dict = {"street": st, "city": ct}
    if province.strip():
        address["province"] = province.strip()
    if postal_code.strip():
        address["postalCode"] = postal_code.strip()
    if country.strip():
        address["country"] = country.strip()

    input_obj = {
        "clientId": cid,
        "address": address,
    }

    # Encode property characteristics in notes since Jobber's core property
    # schema doesn't have structured fields for rooms/bathrooms/offices.
    notes_parts = []
    if property_type.strip():
        notes_parts.append(f"Type: {property_type.strip()}")
    if bedrooms:
        notes_parts.append(f"Bedrooms: {bedrooms}")
    if bathrooms:
        notes_parts.append(f"Bathrooms: {bathrooms}")
    if offices:
        notes_parts.append(f"Offices: {offices}")
    if notes_parts:
        input_obj["notes"] = " | ".join(notes_parts)

    try:
        data = jobber_client.execute(_MUTATION_CREATE_PROPERTY, {"input": input_obj})
    except JobberAPIError as e:
        logger.error(
            "jobber_create_property failed",
            extra={"tool": "jobber_create_property", "error": str(e)},
        )
        return f"Jobber API error: {e.detail}"

    result = data.get("data", {}).get("propertyCreate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        detail = "; ".join(f"{e.get('path', '')}: {e.get('message', '')}" for e in user_errors)
        return f"Could not create property: {detail}"

    prop = result.get("property")
    if not prop:
        return "Property creation returned no data."

    prop_id = prop.get("id")
    addr = prop.get("address", {}) or {}
    addr_str = ", ".join(
        v for v in (addr.get("street"), addr.get("city"), addr.get("province"), addr.get("postalCode"))
        if v
    )
    logger.info(
        "Property created",
        extra={"tool": "jobber_create_property", "property_id": prop_id, "client_id": cid},
    )
    return f"Property created: {addr_str} (Property ID: {prop_id})"
