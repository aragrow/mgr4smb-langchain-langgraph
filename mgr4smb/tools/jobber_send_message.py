"""Jobber Send Message — [FUTURE] notify vendor about a new job.

PLACEHOLDER for future implementation. When a new job is booked via
BOOKING_AGENT → JOBBER_SUPPORT_AGENT, this tool will notify the assigned
vendor (e.g. by creating a Jobber note, sending an email via a workflow,
or posting to a messaging integration).

Not wired into any agent yet. Do not include this tool in any agent's
tool list until the implementation is complete.
"""

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def jobber_send_message(job_id_jobber: str, message: str) -> str:
    """[NOT IMPLEMENTED] Send a message / notification to the vendor about a job.

    This is a placeholder. Returns a not-implemented message.

    Args:
        job_id_jobber: The Jobber job ID the message relates to.
        message: The message content to send to the vendor.
    """
    logger.warning(
        "jobber_send_message called but not implemented",
        extra={"tool": "jobber_send_message", "job_id": job_id_jobber},
    )
    return (
        "Vendor notification is not yet implemented. The job has been created, "
        "but no automated message was sent. Please follow up manually."
    )
