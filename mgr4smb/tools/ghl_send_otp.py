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


def _normalize_phone(phone: str) -> str:
    """Return the last 10 significant digits of a phone number for comparison.

    This makes matching robust to:
      - formatting differences ('(952) 228-1752' vs '952-228-1752')
      - optional country code for US/CA numbers ('+19522281752' vs '9522281752')
      - leading zeros, spaces, dots, plus signs

    For numbers shorter than 10 digits (likely an input mistake), the caller
    still gets back whatever digits are present so the explicit mismatch
    branch fires rather than a silent false-positive match.
    """
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


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

        # Resolve the human-readable field keys → real GHL field ids.
        # GHL silently ignores PUTs that use the key form, leaving the
        # fields blank (which leaves the workflow email blank too).
        code_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_code_field_key)
        expiry_field_id = ghl_client.resolve_custom_field_id(settings.ghl_otp_expiry_field_key)

        # Send-once guard: if there's already an unexpired code on this
        # contact, reuse it rather than overwriting. This enforces the
        # policy that a verification code is issued ONCE per active
        # verification window — if the user didn't enter it correctly the
        # first time, they get their retries against the same code, not a
        # fresh one. When the code actually expires, verify_otp clears it,
        # so a subsequent send_otp call naturally generates a new one.
        fresh = ghl_client.fetch_contact(contact_id)
        existing_code = ""
        existing_expiry = ""
        for f in fresh.get("customFields", []):
            fid = f.get("id", "")
            if fid == code_field_id:
                existing_code = (f.get("value", "") or "").strip()
            elif fid == expiry_field_id:
                existing_expiry = (f.get("value", "") or "").strip()

        if existing_code and existing_expiry:
            try:
                exp_dt = datetime.fromisoformat(existing_expiry)
                if datetime.now(timezone.utc) < exp_dt:
                    logger.info(
                        "OTP reuse (unexpired code exists)",
                        extra={"tool": "ghl_send_otp", "contact_id": contact_id},
                    )
                    return (
                        "OTP_SENT: A verification code was already sent to the "
                        "email on file. Please check your inbox (and spam) — the "
                        "existing code is still valid."
                    )
            except ValueError:
                # Malformed expiry timestamp — treat as no active code
                pass

        # Generate OTP
        otp_code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(minutes=settings.ghl_otp_lifetime_minutes)
        ).isoformat()

        # Store OTP on the contact (triggers GHL workflow to email the code)
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
        logger.error("ghl_send_otp failed", extra={"tool": "ghl_send_otp"}, exc_info=True)
        raise GHLAPIError(500, str(e)) from e

    logger.info("OTP sent", extra={"tool": "ghl_send_otp", "contact_id": contact_id})
    return "OTP_SENT: A verification code has been sent to the email on file."
