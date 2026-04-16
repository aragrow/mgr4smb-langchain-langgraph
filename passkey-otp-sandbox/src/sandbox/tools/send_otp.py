"""Send OTP — stores a 6-digit code on the GHL contact.

Writing the code to the configured custom fields triggers the GHL
workflow that actually emails the code to the user.

Behavior for new vs. existing users:

- Existing contact (lookup by email succeeds): verify that the phone
  the user gave matches the record. Mismatch → `OTP_FAILED` and no
  email goes out. This guards against impersonation of someone whose
  email is known but whose phone the attacker doesn't have.
- New contact (lookup misses): create the contact in GHL with the
  email, phone, and optional first/last name the caller supplied, then
  send the OTP to that freshly-created record. The GHL side will
  reject or dedupe a collision on email, so repeats are safe.

The sandbox writes to GHL only at the moment of a sensitive action
(OTP send). Anonymous KB-browsing users never create a contact.
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
def send_otp(
    contact_email: str,
    contact_phone: str,
    first_name: str = "",
    last_name: str = "",
) -> str:
    """Send a 6-digit verification code to the contact's email.

    For an existing contact, verifies that both email and phone match
    before sending. For a new contact (no record found for the email),
    creates the contact with the supplied email + phone + optional
    first/last name, then sends the OTP to it.

    Returns OTP_SENT on success, OTP_FAILED if an existing contact's
    phone doesn't match the one on file (the only case where we refuse
    to send).

    Args:
        contact_email: The user's email address.
        contact_phone: The user's phone number.
        first_name: Optional — only used when creating a new contact.
        last_name: Optional — only used when creating a new contact.
    """
    email = (contact_email or "").strip().lower()
    phone = (contact_phone or "").strip()

    if not email:
        return "OTP_FAILED: An email address is required."
    if not phone:
        return "OTP_FAILED: A phone number is required."

    try:
        contact = ghl_client.search_contact(email)

        if contact is None:
            # New user — this is the first time we're seeing this email
            # AND the caller has just asked for something sensitive (we
            # wouldn't be in send_otp otherwise). Create the contact now.
            logger.info(
                "Creating new GHL contact via send_otp",
                extra={
                    "tool": "send_otp",
                    "email": email,
                    "has_name": bool(first_name.strip() or last_name.strip()),
                },
            )
            contact = ghl_client.create_contact(
                email=email,
                phone=phone,
                first_name=first_name,
                last_name=last_name,
            )
        else:
            # Existing contact — phone MUST match the record, otherwise
            # we'd be willing to email an OTP to a real user that an
            # attacker is trying to impersonate with a wrong phone.
            on_file = contact.get("phone", "")
            if _normalize_phone(phone) != _normalize_phone(on_file):
                logger.warning("OTP rejected: phone mismatch",
                               extra={"tool": "send_otp"})
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
