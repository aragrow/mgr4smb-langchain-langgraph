"""Jobber Get Visits — lists visits for a client, grouped by job."""

import logging

from langchain_core.tools import tool

from mgr4smb.exceptions import JobberAPIError
from mgr4smb.tools import jobber_client

logger = logging.getLogger(__name__)


_QUERY_VISITS = """
query GetVisits($clientId: EncodedId!) {
  client(id: $clientId) {
    jobs(first: 50) {
      nodes {
        id
        title
        visits(first: 50) {
          nodes {
            id
            title
            startAt
            endAt
            visitStatus
            property {
              id
              address {
                street
                city
                province
              }
            }
          }
        }
      }
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
def jobber_get_visits(client_id_jobber: str) -> str:
    """List scheduled and completed visits for a Jobber client, grouped by job.

    Args:
        client_id_jobber: Base64-encoded Jobber client ID (from Get Clients).
    """
    cid = (client_id_jobber or "").strip()
    if not cid:
        return "Error: A Jobber client ID is required."

    try:
        data = jobber_client.execute(_QUERY_VISITS, {"clientId": cid})
    except JobberAPIError as e:
        logger.error("jobber_get_visits failed", extra={"tool": "jobber_get_visits", "error": str(e)})
        return f"Jobber API error: {e.detail}"

    client = data.get("data", {}).get("client")
    if not client:
        return f"No Jobber client found for ID: {cid}"

    jobs = client.get("jobs", {}).get("nodes", [])
    total_visits = sum(len(j.get("visits", {}).get("nodes", [])) for j in jobs)

    if not jobs or total_visits == 0:
        return f"No visits found for client ID: {cid}"

    lines = [f"Visits ({total_visits}) across {len(jobs)} job(s) for client {cid}:"]
    for j in jobs:
        job_title = j.get("title", "Untitled")
        visits = j.get("visits", {}).get("nodes", [])
        if not visits:
            continue
        lines.append(f"  Job: {job_title} (ID: {j.get('id')})")
        for v in visits:
            v_title = v.get("title", "Visit")
            status = v.get("visitStatus", "")
            start = v.get("startAt", "")
            end = v.get("endAt", "")
            prop = _format_address((v.get("property") or {}).get("address"))
            lines.append(
                f"    - {v_title} | {status} | {start} → {end} | {prop} | ID: {v.get('id')}"
            )

    logger.info(
        "Visits returned",
        extra={"tool": "jobber_get_visits", "client_id": cid, "count": total_visits},
    )
    return "\n".join(lines)
