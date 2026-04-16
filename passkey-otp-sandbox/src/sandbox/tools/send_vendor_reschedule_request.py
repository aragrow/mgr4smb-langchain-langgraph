"""Send a reschedule request to the vendor via the GHL workflow pipeline.

The vendor_notifier_agent composes a human-readable email body, then
calls this tool to persist it. The tool:

  1. Looks up the caller's GHL contact (by email).
  2. Writes the composed message to the configured
     `GHL_RESCHEDULE_REQUEST_FIELD_KEY` custom field.
  3. Bumps the `GHL_RESCHEDULE_REQUESTED_AT_FIELD_KEY` custom field
     to the current UTC timestamp. This guaranteed change is what
     triggers the GHL workflow that actually emails the vendor
     (same pattern as the OTP workflow).

No email is sent directly from Python — routing the message through
GHL lets the customer (who owns the GHL account) control template,
recipient, retries, etc. entirely in their workflow editor.

The agent never calls this tool twice for one request — the prompt
enforces a single send after an explicit confirmation from the user.
"""

import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

from sandbox.config import settings
from sandbox.exceptions import GHLAPIError
from sandbox.tools import ghl_client

logger = logging.getLogger(__name__)


@tool
def send_vendor_reschedule_request(
    contact_email: str,
    property_address: str,
    job_title: str,
    current_visit_start: str,
    proposed_new_time: str,
    email_subject: str,
    email_body: str,
) -> str:
    """Dispatch a reschedule request to the vendor via GHL.

    Writes the composed email subject + body to the configured GHL
    custom fields on the caller's contact, then bumps the "requested
    at" timestamp field so the GHL workflow fires and emails the
    vendor.

    Returns "RESCHEDULE_SENT" on success, "RESCHEDULE_FAILED: <reason>"
    otherwise.

    Args:
        contact_email: The caller's email (used to find their GHL contact).
        property_address: Full service address (free-form string).
        job_title: Current job / service name.
        current_visit_start: When the visit is currently scheduled
            (ISO string or any legible form).
        proposed_new_time: What the caller is asking to move it to
            (ISO or natural-language).
        email_subject: Pre-composed email subject line.
        email_body: Pre-composed email body (plain text or markdown).
    """
    email = (contact_email or "").strip().lower()
    if not email:
        return "RESCHEDULE_FAILED: Missing caller email."
    if not email_body.strip() or not email_subject.strip():
        return "RESCHEDULE_FAILED: Missing email subject or body."

    try:
        contact = ghl_client.search_contact(email)
        if not contact:
            return (
                "RESCHEDULE_FAILED: Could not find a GHL contact for "
                f"{email}. Ask the user to complete OTP verification first "
                "so their contact is on file."
            )
        contact_id = contact["id"]

        request_field_id = ghl_client.resolve_custom_field_id(
            settings.ghl_reschedule_request_field_key
        )
        timestamp_field_id = ghl_client.resolve_custom_field_id(
            settings.ghl_reschedule_requested_at_field_key
        )

        # Combine everything into the one long-text field. The GHL
        # workflow can parse it (or just paste it straight into the
        # email body). Keep it structured so the vendor email is
        # easy to read without any template work.
        payload = (
            f"SUBJECT: {email_subject}\n\n"
            f"Property: {property_address}\n"
            f"Job / Service: {job_title}\n"
            f"Current visit: {current_visit_start}\n"
            f"Proposed new time: {proposed_new_time}\n"
            f"Caller email: {email}\n"
            f"Vendor: {settings.vendor_name}\n"
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
                    {"id": request_field_id, "value": payload},
                    {"id": timestamp_field_id, "value": now_iso},
                ],
            },
        )
        resp.raise_for_status()

    except GHLAPIError:
        raise
    except Exception as e:
        logger.error(
            "send_vendor_reschedule_request failed",
            extra={"tool": "send_vendor_reschedule_request"},
            exc_info=True,
        )
        raise GHLAPIError(500, str(e)) from e

    logger.info(
        "Vendor reschedule request dispatched",
        extra={
            "tool": "send_vendor_reschedule_request",
            "contact_id": contact_id,
            "property": property_address[:80],
        },
    )
    return "RESCHEDULE_SENT: The vendor has been notified."
