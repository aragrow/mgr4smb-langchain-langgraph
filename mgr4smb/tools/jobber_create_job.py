"""Jobber Create Job — creates a new job tied to a client and property."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_MUTATION_CREATE_JOB = """
mutation CreateJob($input: JobCreateInput!) {
  jobCreate(input: $input) {
    job {
      id
      title
      jobStatus
      startAt
      endAt
    }
    userErrors { message path }
  }
}
"""


@tool
def jobber_create_job(
    client_id_jobber: str,
    property_id_jobber: str,
    title: str,
    description: str = "",
    start_at: str = "",
    end_at: str = "",
) -> str:
    """Create a new job in Jobber tied to an existing client and property.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID.
        property_id_jobber: Base64-encoded Jobber property ID.
        title: Job title / service name (e.g. "Deep cleaning").
        description: Optional job description.
        start_at: Optional ISO 8601 start datetime.
        end_at: Optional ISO 8601 end datetime.
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
        "clientId": cid,
        "propertyId": pid,
        "title": ttl,
    }
    if description.strip():
        input_obj["description"] = description.strip()
    if start_at.strip():
        input_obj["startAt"] = start_at.strip()
    if end_at.strip():
        input_obj["endAt"] = end_at.strip()

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
        extra={"tool": "jobber_create_job", "job_id": job_id, "client_id": cid, "property_id": pid},
    )
    return (
        f"Job created: '{job.get('title')}' — status: {job.get('jobStatus')} "
        f"— scheduled: {job.get('startAt') or 'TBD'} → {job.get('endAt') or 'TBD'} "
        f"(Job ID: {job_id})"
    )
