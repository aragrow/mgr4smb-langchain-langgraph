"""Jobber Get Jobs — lists jobs for a client."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_QUERY_JOBS = """
query GetJobs($clientId: EncodedId!, $cursor: String) {
  client(id: $clientId) {
    jobs(after: $cursor, first: 50) {
      nodes {
        id
        title
        jobStatus
        startAt
        endAt
        total
        property {
          id
          address {
            street
            city
            province
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def _format_address(addr: dict | None) -> str:
    if not addr:
        return ""
    parts = [addr.get("street", ""), addr.get("city", ""), addr.get("province", "")]
    return ", ".join(p for p in parts if p)


@tool
def jobber_get_jobs(client_id_jobber: str) -> str:
    """List the jobs for a single Jobber client.

    Returns title, status, dates, total, and the property each job is on.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID (from Get Clients).
    """
    cid = (client_id_jobber or "").strip()
    if not cid:
        return "Error: A Jobber client ID is required."

    try:
        data = jobber_client.execute(_QUERY_JOBS, {"clientId": cid, "cursor": None})
    except JobberAPIError as e:
        logger.error("jobber_get_jobs failed", extra={"tool": "jobber_get_jobs", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    client = data.get("data", {}).get("client")
    if not client:
        return f"No Jobber client found for ID: {cid}"

    jobs = client.get("jobs", {}).get("nodes", [])
    if not jobs:
        return f"No jobs found for client ID: {cid}"

    lines = [f"Jobs ({len(jobs)}) for client {cid}:"]
    for j in jobs:
        title = j.get("title", "Untitled")
        status = j.get("jobStatus", "")
        start = j.get("startAt", "")
        end = j.get("endAt", "")
        total = j.get("total", "")
        property_addr = _format_address((j.get("property") or {}).get("address"))
        lines.append(
            f"- {title} | {status} | {start} → {end} | ${total} | {property_addr} | ID: {j.get('id')}"
        )

    logger.info(
        "Jobs returned",
        extra={"tool": "jobber_get_jobs", "client_id": cid, "count": len(jobs)},
    )
    return "\n".join(lines)
