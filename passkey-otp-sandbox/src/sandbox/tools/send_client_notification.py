"""Send a notification email to the CLIENT via the GHL workflow pipeline.

Mirror of send_vendor_reschedule_request, but aimed at the caller
instead of the scheduling team. Any agent that wants to email the
client out-of-band (confirmation after a reschedule request, booking
acknowledgement, status update, etc.) can delegate to
client_notifier_agent, which composes the message and calls this
tool to dispatch it.

The tool writes the composed payload to the contact's
GHL_CLIENT_NOTIFICATION_FIELD_KEY custom field and bumps
GHL_CLIENT_NOTIFICATION_AT_FIELD_KEY to the current UTC timestamp.
A GHL workflow triggered on the timestamp change emails the caller.
"""

import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


@tool
def send_client_notification(
    contact_email: str,
    email_subject: str,
    email_body: str,
    reason: str = "general",
) -> str:
    """Dispatch a notification email to the caller via GHL.

    Writes the composed email subject + body to the configured GHL
    custom fields on the caller's contact, then bumps the "notified
    at" timestamp field so the GHL workflow fires and emails them.

    Returns "CLIENT_NOTIFIED" on success or
    "CLIENT_NOTIFICATION_FAILED: <reason>" otherwise.

    Args:
        contact_email: The caller's email (used to find their GHL contact).
        email_subject: Pre-composed subject line.
        email_body: Pre-composed body (plain text).
        reason: Short category tag for bookkeeping — e.g.
            "reschedule_confirmation", "booking_confirmation",
            "general". Persisted inside the payload so the GHL
            workflow can branch on it if needed.
    """
    email = (contact_email or "").strip().lower()
    if not email:
        return "CLIENT_NOTIFICATION_FAILED: Missing contact email."
    if not email_subject.strip() or not email_body.strip():
        return "CLIENT_NOTIFICATION_FAILED: Missing email subject or body."

    try:
        contact = ghl_client.search_contact(email)
        if not contact:
            return (
                "CLIENT_NOTIFICATION_FAILED: Could not find a GHL contact "
                f"for {email}. The caller must complete OTP verification "
                "first so their contact is on file."
            )
        contact_id = contact["id"]

        message_field_id = ghl_client.resolve_custom_field_id(
            settings.ghl_client_notification_field_key
        )
        timestamp_field_id = ghl_client.resolve_custom_field_id(
            settings.ghl_client_notification_at_field_key
        )

        payload = (
            f"SUBJECT: {email_subject}\n"
            f"REASON: {reason.strip() or 'general'}\n"
            f"RECIPIENT: {email}\n"
            "\n"
            "--- BODY ---\n"
            f"{email_body}"
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        client = ghl_client.get_client()
        resp = client.put(
            f"/contacts/{contact_id}",
            json={
                "customFields": [
                    {"id": message_field_id, "value": payload},
                    {"id": timestamp_field_id, "value": now_iso},
                ],
            },
        )
        resp.raise_for_status()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error(
            "send_client_notification failed",
            extra={"tool": "send_client_notification"},
            exc_info=True,
        )
        raise GHLAPIError(500, str(e)) from e

    logger.info(
        "Client notification dispatched",
        extra={
            "tool": "send_client_notification",
            "contact_id": contact_id,
            "reason": reason,
        },
    )
    return "CLIENT_NOTIFIED: The caller has been emailed."
