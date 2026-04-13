"""Retrieve Jobber jobs for a client, identified by email.

Flow:
    1. Prompt for (or --email) the client's email.
    2. jobber_get_clients → captures the Jobber client ID.
    3. jobber_get_jobs → prints title, status, dates, total, and the
       property each job is on.

Read-only.

Usage:
    python scripts/jobber_jobs_by_email.py
    python scripts/jobber_jobs_by_email.py --email jane@example.com
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _jobber_by_email import (  # noqa: E402
    banner,
    build_arg_parser,
    err,
    indent,
    line,
    ok,
    read_email,
    resolve_client_id,
    warn,
)


def main() -> int:
    args = build_arg_parser(
        "Fetch Jobber jobs (title/status/dates/total/property) for a client by email."
    ).parse_args()
    banner("Jobber — jobs by email")

    email = read_email(args)
    if email is None:
        return 1

    print()
    print(f"  Searching Jobber for client with email: {email}")
    client_id, clients_result = resolve_client_id(email)
    print()
    print(indent(clients_result))

    if client_id is None:
        print()
        warn(
            f"No Jobber client ID found for {email}. "
            "The email may not be on file."
        )
        return 1

    print()
    print(line("─"))
    print(f"  Fetching jobs for Jobber client ID: {client_id}")
    print(line("─"))

    try:
        from mgr4smb.tools.jobber_get_jobs import jobber_get_jobs
    except Exception as e:
        err(f"Could not import jobber_get_jobs: {e}")
        return 1

    try:
        jobs_result = jobber_get_jobs.invoke({"client_id_jobber": client_id})
    except Exception as e:
        err(f"jobber_get_jobs raised: {type(e).__name__}: {e}")
        return 1

    print()
    print(indent(jobs_result))
    print()
    ok("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
