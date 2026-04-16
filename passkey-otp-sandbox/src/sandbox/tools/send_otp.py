"""Send OTP — stores a 6-digit code on the GHL contact.

Ported from mgr4smb/tools/ghl_send_otp.py. Keeps the public tool name
`send_otp` so the authenticator prompt doesn't change.

Security: verifies BOTH email and phone match the contact record before
generating the code. If either doesn't match, the request is rejected
with "OTP_FAILED" — no email is sent.

Writing the code to the configured custom fields triggers the GHL
workflow that actually emails the code to the user.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    """Last-10-digits normalisation — robust to formatting / country code."""
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@tool
def send_otp(contact_email: str, contact_phone: str) -> str:
    """Send a 6-digit verification code to the contact's email.

    Verifies that both email and phone match the contact on file before
    sending. Returns OTP_SENT on success, OTP_FAILED if the info doesn't
    match.

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
        contact = ghl_client.search_contact(email)

        if not contact:
            logger.warning("OTP rejected: no contact for email", extra={"tool": "send_otp"})
            return "OTP_FAILED: The information provided does not match our records."

        contact_phone_on_file = contact.get("phone", "")
        if _normalize_phone(phone) != _normalize_phone(contact_phone_on_file):
            logger.warning("OTP rejected: phone mismatch", extra={"tool": "send_otp"})
            return "OTP_FAILED: The information provided does not match our records."

        contact_id = contact["id"]

        code_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_code_field_key)
        expiry_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_expiry_field_key)

        # Session-level "send once" is enforced upstream by the
        # authenticator prompt. Here we always overwrite any stale code
        # from a previous session, which is the desired behaviour.
        otp_code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(minutes=settings.ghl_otp_lifetime_minutes)
        ).isoformat()

        client = ghl_client.get_client()
        resp = client.put(
            f"/contacts/{contact_id}",
            json={
                "customFields": [
                    {"id": code_field_id, "value": otp_code},
                    {"id": expiry_field_id, "value": expires_at},
                ],
            },
        )
        resp.raise_for_status()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error("send_otp failed", extra={"tool": "send_otp"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    logger.info("OTP sent", extra={"tool": "send_otp", "contact_id": contact_id})
    return "OTP_SENT: A verification code has been sent to the email on file."
