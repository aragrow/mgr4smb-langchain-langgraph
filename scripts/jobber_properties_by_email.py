"""
Retrieve Jobber service properties for a client, identified by email.

Flow:
    1. Prompt for the client's email (or take it from --email).
    2. Call jobber_get_clients with that email → capture the Jobber
       client ID from the response.
    3. Call jobber_get_properties with that client ID → print the
       addresses.

Read-only; no Jobber data is written.

Usage:
    source .venv/bin/activate

    # Interactive
    python scripts/jobber_properties_by_email.py

    # Scripted
    python scripts/jobber_properties_by_email.py --email jane@example.com
"""

import argparse
import re
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.logging_config import setup_logging  # noqa: E402


def _line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def _indent(text: str, n: int = 4) -> str:
    prefix = " " * n
    return "\n".join(prefix + ln for ln in (text or "").splitlines())


def _ok(msg: str) -> None:
    print(f"\033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"\033[33m!\033[0m {msg}")


def _err(msg: str) -> None:
    print(f"\033[31m✗\033[0m {msg}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Jobber service properties for a client by email."
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Client's email address. If omitted, you'll be prompted.",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")

    print(_line("═"))
    print("  Jobber — properties by email")
    print(_line("═"))

    # --- 1) get email ---
    email = (args.email or "").strip()
    if not email:
        try:
            email = input("\n  Client email ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled.")
            return 1

    if not email:
        _err("No email provided.")
        return 1

    if "@" not in email:
        _warn(f"{email!r} doesn't look like an email — continuing anyway.")

    # --- 2) search Jobber clients by email ---
    print()
    print(f"  Searching Jobber for client with email: {email}")
    try:
        from mgr4smb.tools.jobber_get_clients import jobber_get_clients
    except Exception as e:
        _err(f"Could not import jobber_get_clients: {e}")
        return 1

    try:
        clients_result = jobber_get_clients.invoke({"search_value": email})
    except Exception as e:
        _err(f"jobber_get_clients raised: {type(e).__name__}: {e}")
        return 1

    print()
    print(_indent(clients_result))

    # --- 3) extract the first client ID ---
    ids = re.findall(r"ID:\s*([A-Za-z0-9+/=]{12,})", clients_result)
    if not ids:
        print()
        _warn(
            f"No Jobber client ID found in the search result for {email}. "
            "The email may not be on file."
        )
        return 1

    if len(ids) > 1:
        print()
        _warn(
            f"Multiple matches found ({len(ids)}). Using the first one: {ids[0]}"
        )

    client_id = ids[0]

    # --- 4) fetch properties ---
    print()
    print(_line("─"))
    print(f"  Fetching properties for Jobber client ID: {client_id}")
    print(_line("─"))

    try:
        from mgr4smb.tools.jobber_get_properties import jobber_get_properties
    except Exception as e:
        _err(f"Could not import jobber_get_properties: {e}")
        return 1

    try:
        properties_result = jobber_get_properties.invoke(
            {"client_id_jobber": client_id}
        )
    except Exception as e:
        _err(f"jobber_get_properties raised: {type(e).__name__}: {e}")
        return 1

    print()
    print(_indent(properties_result))

    print()
    _ok("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
