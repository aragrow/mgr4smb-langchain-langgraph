"""Jobber Create Property — creates a service property for a client.

Schema notes (verified via live introspection — see Jobber developer docs):
- propertyCreate takes TWO top-level args: clientId (EncodedId) and
  input (PropertyCreateInput). clientId is NOT nested inside input.
- PropertyCreateInput wraps a single `properties: PropertyAttributes`
  field. PropertyAttributes exposes: address, contacts, contactsToAssign,
  customFields, taxRateId, name. There is NO `notes` field on
  PropertyAttributes.
- AddressAttributes uses `street1` / `street2` (not `street`).
- Jobber does not store structured data for house/apartment/office or
  bedroom/bathroom counts. We fold that detail into the property's
  `name` field so it's still visible in the Jobber UI (e.g.
  "House · 3 BR / 2 BA"). Upgrading to custom fields is a future option.
"""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_MUTATION_CREATE_PROPERTY = """
mutation CreateProperty($clientId: EncodedId!, $input: PropertyCreateInput!) {
  propertyCreate(clientId: $clientId, input: $input) {
    property {
      id
      address {
        street1
        street2
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


def _property_name(property_type: str, bedrooms: int, bathrooms: int, offices: int) -> str:
    """Fold property characteristics into a human-readable name string.

    Jobber's core Property schema has no structured fields for type / rooms /
    bathrooms / offices. We encode those here so they remain visible on the
    property record in the Jobber UI.
    """
    parts: list[str] = []
    if property_type.strip():
        parts.append(property_type.strip().capitalize())
    room_bits: list[str] = []
    if bedrooms:
        room_bits.append(f"{bedrooms} BR")
    if bathrooms:
        room_bits.append(f"{bathrooms} BA")
    if offices:
        room_bits.append(f"{offices} OFC")
    if room_bits:
        parts.append(" / ".join(room_bits))
    return " · ".join(parts)


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
        street: Street address (maps to Jobber's `street1`).
        city: City.
        province: State or province.
        postal_code: ZIP or postal code.
        country: Country.
        property_type: "house", "apartment", or "office". Encoded in the
            property's name since Jobber has no structured field for it.
        bedrooms: Number of bedrooms (for house/apartment). Encoded in name.
        bathrooms: Number of bathrooms. Encoded in name.
        offices: Number of offices (for office type). Encoded in name.
    """
    cid = (client_id_jobber or "").strip()
    st = (street or "").strip()
    ct = (city or "").strip()

    if not cid:
        return "Error: A Jobber client ID is required."
    if not st or not ct:
        return "Error: Street and city are required."

    # AddressAttributes uses `street1` (and optional `street2`), NOT `street`.
    address: dict = {"street1": st, "city": ct}
    if province.strip():
        address["province"] = province.strip()
    if postal_code.strip():
        address["postalCode"] = postal_code.strip()
    if country.strip():
        address["country"] = country.strip()

    property_attrs: dict = {"address": address}
    name = _property_name(property_type, bedrooms, bathrooms, offices)
    if name:
        property_attrs["name"] = name

    # Top-level `clientId` arg; input wraps `properties: PropertyAttributes`.
    variables = {
        "clientId": cid,
        "input": {"properties": property_attrs},
    }

    try:
        data = jobber_client.execute(_MUTATION_CREATE_PROPERTY, variables)
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
        v for v in (
            addr.get("street1"),
            addr.get("street2"),
            addr.get("city"),
            addr.get("province"),
            addr.get("postalCode"),
        )
        if v
    )
    logger.info(
        "Property created",
        extra={"tool": "jobber_create_property", "property_id": prop_id, "client_id": cid},
    )
    return f"Property created: {addr_str} (Property ID: {prop_id})"
