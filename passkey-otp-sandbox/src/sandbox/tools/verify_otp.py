"""Verify OTP — validates a user-provided code against the GHL stored code.

Ported from mgr4smb/tools/ghl_verify_otp.py. Keeps the public tool name
`verify_otp` so the authenticator prompt doesn't change.

On success, invalidates the code by back-dating the expiry field. We do
NOT clear the code field itself — clearing it re-fires the GHL workflow
and sends a second (blank) email to the user. Back-dating the expiry is
enough: any subsequent verify attempt will see the past timestamp and
reject, same as if the code had been cleared.
"""

import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


def _invalidate_otp(client, contact_id: str) -> None:
    """Back-date expiry to 1970 so the code is rejected on any replay."""
    try:
        expiry_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_expiry_field_key)
        past = datetime.fromtimestamp(0, tz=timezone.utc).isoformat()
        client.put(
            f"/contacts/{contact_id}",
            json={
                "customFields": [
                    {"id": expiry_field_id, "value": past},
                ],
            },
        )
    except Exception:
        logger.warning("Failed to invalidate OTP expiry", extra={"contact_id": contact_id})


@tool
def verify_otp(contact_identifier: str, otp_code: str) -> str:
    """Validate a 6-digit OTP code provided by the user.

    Returns VERIFIED on success, UNVERIFIED with a reason on failure.

    Args:
        contact_identifier: Email or phone to identify the contact.
        otp_code: The 6-digit code the user received via email.
    """
    identifier = (contact_identifier or "").strip()
    code = (otp_code or "").strip()

    if not identifier:
        return "UNVERIFIED: An email or phone is required."
    if not code:
        return "UNVERIFIED: A verification code is required."

    try:
        contact = ghl_client.search_contact(identifier)
        if not contact:
            return "UNVERIFIED: Contact not found."

        contact_id = contact["id"]
        client = ghl_client.get_client()

        # Fresh GET — /contacts/search's custom-field values lag by several
        # seconds after a PUT, so we'd never see the newly-written code.
        fresh = ghl_client.fetch_contact(contact_id)

        code_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_code_field_key)
        expiry_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_expiry_field_key)

        stored_code = ""
        stored_expiry = ""
        for field in fresh.get("customFields", []):
            fid = field.get("id", "")
            if fid == code_field_id:
                stored_code = (field.get("value", "") or "").strip()
            elif fid == expiry_field_id:
                stored_expiry = (field.get("value", "") or "").strip()

        if not stored_code:
            return "UNVERIFIED: No verification code was sent. Please request a new one."

        if stored_expiry:
            try:
                expiry_dt = datetime.fromisoformat(stored_expiry)
                if datetime.now(timezone.utc) > expiry_dt:
                    logger.warning("OTP expired", extra={"tool": "verify_otp", "contact_id": contact_id})
                    return "UNVERIFIED: The verification code has expired. Please request a new one."
            except ValueError:
                pass

        if code != stored_code:
            logger.warning("OTP wrong code", extra={"tool": "verify_otp", "contact_id": contact_id})
            return "UNVERIFIED: The code you entered is incorrect. Please try again."

        _invalidate_otp(client, contact_id)

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("verify_otp failed", extra={"tool": "verify_otp"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    logger.info("OTP verified", extra={"tool": "verify_otp", "contact_id": contact_id})
    return "VERIFIED: Identity confirmed successfully."
