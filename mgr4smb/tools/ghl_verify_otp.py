"""GHL Verify OTP — validates a user-provided OTP code against the stored code.

Clears the code after verification (success or expiry) to prevent reuse.
"""

import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

from mgr4smb.config import settings
from mgr4smb.exceptions import GHLAPIError
from mgr4smb.tools import ghl_client

logger = logging.getLogger(__name__)


def _invalidate_otp(client, contact_id: str) -> None:
    """Mark the stored OTP as consumed by back-dating its expiry field.

    We used to clear BOTH the code and expiry fields, but the client's GHL
    workflow that sends the OTP email fires on any change to `otp_code` —
    clearing it to empty triggered a second email containing a blank code.
    So we now leave the code field alone and ONLY invalidate by writing a
    past timestamp into the expiry field. ghl_verify_otp rejects any code
    whose stored expiry is in the past, so a replay with the same code
    fails the same as a clear did — without firing the email workflow.
    """
    try:
        expiry_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_expiry_field_key)
        # 1970-01-01 is unambiguously "consumed" for any reader of this field.
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
def ghl_verify_otp(contact_identifier: str, otp_code: str) -> str:
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
        # Resolve identifier → contact_id via search (search is fine here —
        # we only need the id, not the custom-field values).
        contact = ghl_client.search_contact(identifier)
        if not contact:
            return "UNVERIFIED: Contact not found."

        contact_id = contact["id"]
        client = ghl_client.get_client()

        # IMPORTANT: re-fetch via GET /contacts/{id} to get FRESH custom
        # field values. GHL's /contacts/search index lags behind PUTs by
        # several seconds, so it would still show the previous OTP code
        # (or empty) even after ghl_send_otp wrote a new one a moment ago.
        fresh = ghl_client.fetch_contact(contact_id)

        # Read stored OTP from custom fields. GHL returns customFields with
        # `id` populated and `key=None`, so we must match on field id.
        # Resolve our human-readable keys to ids first, then look them up.
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

        # Check expiry
        if stored_expiry:
            try:
                expiry_dt = datetime.fromisoformat(stored_expiry)
                if datetime.now(timezone.utc) > expiry_dt:
                    # Already expired — nothing new to invalidate. Don't
                    # write anything back; that would re-trigger workflows
                    # on the code field for no reason.
                    logger.warning("OTP expired", extra={"tool": "ghl_verify_otp", "contact_id": contact_id})
                    return "UNVERIFIED: The verification code has expired. Please request a new one."
            except ValueError:
                pass

        # Compare codes
        if code != stored_code:
            logger.warning("OTP wrong code", extra={"tool": "ghl_verify_otp", "contact_id": contact_id})
            return "UNVERIFIED: The code you entered is incorrect. Please try again."

        # Success — invalidate by back-dating expiry only. Do NOT clear the
        # code field: that would re-trigger the GHL email workflow with an
        # empty code.
        _invalidate_otp(client, contact_id)

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("ghl_verify_otp failed", extra={"tool": "ghl_verify_otp"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    logger.info("OTP verified", extra={"tool": "ghl_verify_otp", "contact_id": contact_id})
    return "VERIFIED: Identity confirmed successfully."
