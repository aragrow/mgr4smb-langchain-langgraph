"""Jobber Create Job — creates a new job tied to a client and property.

Schema notes (verified via live introspection):
- Mutation input type is `JobCreateAttributes`, NOT `JobCreateInput`.
- There is NO top-level `clientId` on JobCreateAttributes — Jobber derives
  the client from the property. Only `propertyId` is needed.
- There is NO `description` field either; the closest semantic match is
  `instructions` (shown on the job record).
- Dates live in nested types:
    timeframe.startAt         (ISO8601Date — the start date, no time)
    timeframe.durationValue   (Int — how many units)
    timeframe.durationUnits   (DurationUnit enum — e.g. DAY, HOUR)
  Separate fine-grained time-of-day lives under `scheduling` (startTime /
  endTime), which we don't populate here — the sales/dispatch team will
  typically set specific visit times when they book real visits. For a
  "new job request" flow, a coarse start date is sufficient.
- The Job object returned does NOT have top-level `startAt` / `endAt`;
  we read those from the nested `timeframe` instead.
"""

import logging
from datetime import datetime

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_MUTATION_CREATE_JOB = """
mutation CreateJob($input: JobCreateAttributes!) {
  jobCreate(input: $input) {
    job {
      id
      title
      jobStatus
      instructions
      startAt
      endAt
    }
    userErrors { message path }
  }
}
"""


def _iso_date(value: str) -> str | None:
    """Extract YYYY-MM-DD from an ISO 8601 string. Returns None if unparseable."""
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    # Full datetimes pass through fromisoformat after stripping trailing Z
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        # If the caller already passed a YYYY-MM-DD string, use it verbatim
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        return None


@tool
def jobber_create_job(
    client_id_jobber: str,
    property_id_jobber: str,
    title: str,
    description: str = "",
    start_at: str = "",
    end_at: str = "",
) -> str:
    """Create a new job in Jobber tied to an existing property.

    Note: Jobber derives the client from the property, so `client_id_jobber`
    is accepted for API consistency with the rest of the toolkit but is
    NOT sent to Jobber.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID (validated, not sent).
        property_id_jobber: Base64-encoded Jobber property ID (required).
        title: Job title / service name (e.g. "Deep cleaning").
        description: Optional description — mapped to Jobber's `instructions`.
        start_at: Optional ISO 8601 start datetime. The date portion is used
            for Jobber's timeframe.startAt; the time portion is ignored
            (schedule fine-grained visit times via jobber_support_agent
            after booking).
        end_at: Accepted for API symmetry but currently ignored (Jobber's
            JobCreateAttributes expresses end via durationValue/durationUnits
            rather than a raw end timestamp; duration fitting is out of
            scope for a "new job request" flow).
    """
    cid = (client_id_jobber or "").strip()
    pid = (property_id_jobber or "").strip()
    ttl = (title or "").strip()

    if not cid:
        return "Error: A Jobber client ID is required."
    if not pid:
        return "Error: A Jobber property ID is required."
    if not ttl:
        return "Error: A job title is required."

    input_obj: dict = {
        "propertyId": pid,
        "title": ttl,
    }
    if description.strip():
        input_obj["instructions"] = description.strip()

    # The parameter is accepted for API symmetry (some callers pass both
    # start_at and end_at) but is intentionally NOT forwarded to Jobber.
    # JobCreateAttributes expresses duration via
    # `timeframe.durationValue` + `timeframe.durationUnits`, not a raw
    # end timestamp. Fitting an arbitrary duration is out of scope for a
    # "new job request" flow; dispatch sets specific visit times later.
    # We log at DEBUG so there's a trail when callers pass end_at.
    if end_at and end_at.strip():
        logger.debug(
            "jobber_create_job: end_at provided but not forwarded to Jobber",
            extra={"tool": "jobber_create_job", "end_at": end_at.strip()},
        )

    start_date = _iso_date(start_at)
    if start_date:
        input_obj["timeframe"] = {"startAt": start_date}

    try:
        data = jobber_client.execute(_MUTATION_CREATE_JOB, {"input": input_obj})
    except JobberAPIError as e:
        logger.error("jobber_create_job failed", extra={"tool": "jobber_create_job", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    result = data.get("data", {}).get("jobCreate", {})
    user_errors = result.get("userErrors", [])
    if user_errors:
        detail = "; ".join(f"{e.get('path', '')}: {e.get('message', '')}" for e in user_errors)
        return f"Could not create job: {detail}"

    job = result.get("job")
    if not job:
        return "Job creation returned no data."

    job_id = job.get("id")
    logger.info(
        "Job created",
        extra={"tool": "jobber_create_job", "job_id": job_id, "property_id": pid},
    )
    return (
        f"Job created: '{job.get('title')}' — status: {job.get('jobStatus')} "
        f"— scheduled: {job.get('startAt') or 'TBD'} → {job.get('endAt') or 'TBD'} "
        f"(Job ID: {job_id})"
    )
