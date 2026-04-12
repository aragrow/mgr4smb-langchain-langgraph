"""GHL Send OTP — generates and stores a 6-digit OTP on the GHL contact.

Security: Verifies BOTH email and phone match the contact record before
generating the code. If either doesn't match, the request is rejected.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from mgr4smb.config import settings
from mgr4smb.exceptions import GHLAPIError
from mgr4smb.tools import ghl_client

logger = logging.getLogger(__name__)

# GHL custom field keys for OTP storage
OTP_CODE_FIELD_KEY = "contact.otp_code"
OTP_EXPIRY_FIELD_KEY = "contact.otp_expires_at"
OTP_LIFETIME_MINUTES = 15


def _normalize_phone(phone: str) -> str:
    """Strip non-digit chars for comparison."""
    return "".join(c for c in phone if c.isdigit())


@tool
def ghl_send_otp(contact_email: str, contact_phone: str) -> str:
    """Send a 6-digit verification code to the contact's email.

    Verifies that both email and phone match the contact on file before sending.
    Returns OTP_SENT on success, OTP_FAILED if the info doesn't match.

    Args:
        contact_email: The user's email address.
        contact_phone: The user's phone number.
    """
    email = (contact_email or "").strip().lower()
    phone = (contact_phone or "").strip()

    if not email:
        return "OTP_FAILED: An email address is required."
    if not phone:
        return "OTP_FAILED: A phone number is required."

    try:
        # Look up by email
        contact = ghl_client.search_contact(email)

        if not contact:
            logger.warning("OTP rejected: no contact for email", extra={"tool": "ghl_send_otp"})
            return "OTP_FAILED: The information provided does not match our records."

        # Verify phone matches
        contact_phone_on_file = contact.get("phone", "")
        if _normalize_phone(phone) != _normalize_phone(contact_phone_on_file):
            logger.warning("OTP rejected: phone mismatch", extra={"tool": "ghl_send_otp"})
            return "OTP_FAILED: The information provided does not match our records."

        contact_id = contact["id"]

        # Generate OTP
        otp_code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=OTP_LIFETIME_MINUTES)).isoformat()

        # Store OTP on the contact (triggers GHL workflow to email the code)
        client = ghl_client.get_client()
        resp = client.put(
            f"/contacts/{contact_id}",
            json={
                "customFields": [
                    {"key": OTP_CODE_FIELD_KEY, "value": otp_code},
                    {"key": OTP_EXPIRY_FIELD_KEY, "value": expires_at},
                ],
            },
        )
        resp.raise_for_status()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("ghl_send_otp failed", extra={"tool": "ghl_send_otp"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    logger.info("OTP sent", extra={"tool": "ghl_send_otp", "contact_id": contact_id})
    return "OTP_SENT: A verification code has been sent to the email on file."
