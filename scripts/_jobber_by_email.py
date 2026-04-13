"""Shared helper for the scripts/jobber_*_by_email.py diagnostics.

Each of those scripts does the same first-half work:
  1. Prompt for email (unless passed via --email).
  2. Call jobber_get_clients to resolve the email to a Jobber client ID.
  3. Print the matched client and return the ID for the caller.

Consolidating that logic here keeps each script small and focused on the
resource it actually fetches (jobs / visits / properties / just the client).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.logging_config import setup_logging  # noqa: E402


def line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def indent(text: str, n: int = 4) -> str:
    prefix = " " * n
    return "\n".join(prefix + ln for ln in (text or "").splitlines())


def ok(msg: str) -> None:
    print(f"\033[32m✓\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m!\033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m✗\033[0m {msg}", file=sys.stderr)


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """Standard --email flag + help text for all jobber_*_by_email scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--email",
        default=None,
        help="Client's email address. If omitted, you'll be prompted.",
    )
    return parser


def read_email(args: argparse.Namespace) -> str | None:
    """Get the email from --email or interactively. Returns None on abort."""
    email = (args.email or "").strip()
    if not email:
        try:
            email = input("\n  Client email ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled.")
            return None
    if not email:
        err("No email provided.")
        return None
    if "@" not in email:
        warn(f"{email!r} doesn't look like an email — continuing anyway.")
    return email


def resolve_client_id(email: str) -> tuple[str | None, str]:
    """Search Jobber by email, return (client_id, raw_response_text).

    On no match OR error, client_id is None and raw_response_text carries
    the explanation for the caller to print.
    """
    try:
        from mgr4smb.tools.jobber_get_clients import jobber_get_clients
    except Exception as e:
        return None, f"Could not import jobber_get_clients: {e}"

    try:
        result = jobber_get_clients.invoke({"search_value": email})
    except Exception as e:
        return None, f"jobber_get_clients raised: {type(e).__name__}: {e}"

    ids = re.findall(r"ID:\s*([A-Za-z0-9+/=]{12,})", result)
    if not ids:
        return None, result
    if len(ids) > 1:
        warn(f"Multiple matches found ({len(ids)}). Using the first one: {ids[0]}")
    return ids[0], result


def banner(title: str) -> None:
    setup_logging(level="WARNING")
    print(line("═"))
    print(f"  {title}")
    print(line("═"))
