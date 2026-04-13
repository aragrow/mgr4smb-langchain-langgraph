"""Retrieve the Jobber client record for a given email.

This is the simplest of the jobber_*_by_email scripts — it just runs the
email through jobber_get_clients and prints the match. No second lookup.

Usage:
    python scripts/jobber_client_by_email.py
    python scripts/jobber_client_by_email.py --email jane@example.com
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
)


def main() -> int:
    args = build_arg_parser("Fetch a Jobber client record by email.").parse_args()
    banner("Jobber — client by email")

    email = read_email(args)
    if email is None:
        return 1

    print()
    print(f"  Searching Jobber for client with email: {email}")

    try:
        from mgr4smb.tools.jobber_get_clients import jobber_get_clients
    except Exception as e:
        err(f"Could not import jobber_get_clients: {e}")
        return 1

    try:
        result = jobber_get_clients.invoke({"search_value": email})
    except Exception as e:
        err(f"jobber_get_clients raised: {type(e).__name__}: {e}")
        return 1

    print()
    print(indent(result))
    print()
    ok("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
