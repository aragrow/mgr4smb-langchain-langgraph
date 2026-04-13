"""
Jobber connection diagnostic.

Runs a sequence of live checks against the Jobber GraphQL API to verify
that .env + .tokens.json are correctly configured and every Jobber tool
we ship works end-to-end. Designed to be the first thing you run after
rotating tokens, onboarding a new client, or debugging a Jobber-side
error.

Usage:
    source .venv/bin/activate

    # Basic connectivity (account query only)
    python scripts/test_jobber_connection.py

    # Full tool coverage (also exercises read tools against a known client)
    python scripts/test_jobber_connection.py --client-search "John Smith"
    python scripts/test_jobber_connection.py --client-search john@example.com
    python scripts/test_jobber_connection.py --client-search +15551234567
    python scripts/test_jobber_connection.py --client-id Q2xpZW50OjEyMzQ=

The script NEVER writes to Jobber. Create mutations (new client / property /
job) are intentionally excluded so running this against production can't
pollute the account.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.config import settings  # noqa: E402
from mgr4smb.logging_config import setup_logging  # noqa: E402


# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def _line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def section(label: str) -> None:
    print(f"\n{_line('═')}")
    print(f"  {label}")
    print(_line("═"))


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        mark = "[PASS]"
    else:
        _FAIL += 1
        mark = "[FAIL]"
    msg = f"  {mark} {label}"
    if detail:
        msg += f"\n           {detail}"
    print(msg)


def info(label: str, value: str = "") -> None:
    print(f"  · {label}{': ' + value if value else ''}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_config() -> bool:
    section("1. Configuration (.env + .tokens.json)")

    ok_all = True
    try:
        cid = settings.jobber_client_id
        check(f"JOBBER_CLIENT_ID present (…{cid[-4:]})", bool(cid))
    except Exception as e:
        check("JOBBER_CLIENT_ID present", False, str(e))
        ok_all = False

    try:
        _ = settings.jobber_client_secret
        check("JOBBER_CLIENT_SECRET present", True)
    except Exception as e:
        check("JOBBER_CLIENT_SECRET present", False, str(e))
        ok_all = False

    tokens_path: Path = settings.jobber_tokens_file
    check(f"Tokens file exists at {tokens_path}", tokens_path.exists())
    if not tokens_path.exists():
        info("To bootstrap:", "authorise the Jobber app via OAuth and write")
        info("", f'  {{"access_token": "...", "refresh_token": "..."}}')
        info("", f"to {tokens_path}")
        return False

    try:
        data = json.loads(tokens_path.read_text())
        check(".tokens.json parses as JSON", True)
    except Exception as e:
        check(".tokens.json parses as JSON", False, str(e))
        return False

    has_access = bool(data.get("access_token"))
    has_refresh = bool(data.get("refresh_token"))
    check(".tokens.json has access_token", has_access)
    check(".tokens.json has refresh_token", has_refresh)
    return ok_all and has_access and has_refresh


def check_account() -> dict | None:
    section("2. Baseline GraphQL query (account)")

    from mgr4smb.tools.jobber_client import execute

    try:
        data = execute("query { account { name id } }", {})
    except Exception as e:
        check("account query succeeds", False, f"{type(e).__name__}: {e}")
        return None

    account = (data.get("data") or {}).get("account") or {}
    if not account:
        check("account returned", False, f"raw: {data}")
        return None

    check("account returned", True)
    info("account name", account.get("name", "?"))
    info("account id", account.get("id", "?"))
    return account


def check_token_refresh_behavior() -> None:
    section("3. Token handling")

    from mgr4smb.tools import jobber_client

    # Cache state
    cached = jobber_client._TOKEN_CACHE.get("access_token")
    file_entry = jobber_client._load_token_file()
    check(
        "in-process token cache populated after the baseline call",
        bool(cached),
    )
    check(
        "token file access_token matches in-process cache",
        cached == file_entry.get("access_token"),
        "A mismatch means a refresh happened mid-run — that's fine, just FYI.",
    )

    # We don't forcibly expire the token in this diagnostic (would invalidate
    # the refresh token for everyone). If you want to test refresh end-to-end,
    # edit .tokens.json to make access_token wrong, re-run, and watch the
    # baseline call succeed anyway after the automatic refresh retry.
    info(
        "To force-test refresh manually",
        "edit .tokens.json, corrupt the access_token, re-run — the baseline "
        "call should still succeed via refresh.",
    )


def check_read_tools(client_search: str | None, client_id: str | None) -> None:
    section("4. Read tools (optional)")

    if not client_search and not client_id:
        info(
            "Skipped",
            "pass --client-search <value> or --client-id <base64> to run",
        )
        return

    from mgr4smb.tools.jobber_get_clients import jobber_get_clients
    from mgr4smb.tools.jobber_get_properties import jobber_get_properties
    from mgr4smb.tools.jobber_get_jobs import jobber_get_jobs
    from mgr4smb.tools.jobber_get_visits import jobber_get_visits

    resolved_cid = client_id

    # --- jobber_get_clients ---
    if client_search:
        print()
        info("jobber_get_clients(search_value=", f"{client_search!r})")
        try:
            result = jobber_get_clients.invoke({"search_value": client_search})
            print(f"\n{_indent(result, 4)}\n")
            check("jobber_get_clients returned without raising", True)

            # Extract the first Jobber ID from the result (format: "ID: <base64>")
            m = re.search(r"ID:\s*([A-Za-z0-9+/=]{12,})", result)
            if m and not resolved_cid:
                resolved_cid = m.group(1)
                info("captured client id for subsequent tests", resolved_cid)
        except Exception as e:
            check(
                "jobber_get_clients runs",
                False,
                f"{type(e).__name__}: {e}",
            )

    if not resolved_cid:
        info(
            "No client ID available",
            "get_clients produced no ID (no match?); skipping properties/jobs/visits",
        )
        return

    # --- jobber_get_properties ---
    print()
    info("jobber_get_properties(client_id_jobber=", f"{resolved_cid!r})")
    try:
        result = jobber_get_properties.invoke({"client_id_jobber": resolved_cid})
        print(f"\n{_indent(result, 4)}\n")
        check("jobber_get_properties returned without raising", True)
    except Exception as e:
        check(
            "jobber_get_properties runs",
            False,
            f"{type(e).__name__}: {e}",
        )

    # --- jobber_get_jobs ---
    print()
    info("jobber_get_jobs(client_id_jobber=", f"{resolved_cid!r})")
    try:
        result = jobber_get_jobs.invoke({"client_id_jobber": resolved_cid})
        print(f"\n{_indent(result, 4)}\n")
        check("jobber_get_jobs returned without raising", True)
    except Exception as e:
        check(
            "jobber_get_jobs runs",
            False,
            f"{type(e).__name__}: {e}",
        )

    # --- jobber_get_visits ---
    print()
    info("jobber_get_visits(client_id_jobber=", f"{resolved_cid!r})")
    try:
        result = jobber_get_visits.invoke({"client_id_jobber": resolved_cid})
        print(f"\n{_indent(result, 4)}\n")
        check("jobber_get_visits returned without raising", True)
    except Exception as e:
        check(
            "jobber_get_visits runs",
            False,
            f"{type(e).__name__}: {e}",
        )


def _indent(text: str, n: int) -> str:
    prefix = " " * n
    return "\n".join(prefix + ln for ln in (text or "").splitlines())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Jobber connectivity diagnostic — read-only."
    )
    parser.add_argument(
        "--client-search",
        default=None,
        help="Search value to exercise jobber_get_clients (name/email/phone/ID).",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Base64 Jobber client ID — skips search and goes straight to properties/jobs/visits.",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")

    print(_line("═"))
    print("  Jobber connection diagnostic")
    print(_line("═"))

    if not check_config():
        print(f"\n{_PASS} passed, {_FAIL} failed — aborting (fix config first).")
        return 1

    account = check_account()
    if account is None:
        print(f"\n{_PASS} passed, {_FAIL} failed — aborting (auth failed).")
        return 1

    check_token_refresh_behavior()
    check_read_tools(args.client_search, args.client_id)

    print()
    print(_line("═"))
    if _FAIL == 0:
        print(f"  All {_PASS} checks passed.")
        return 0
    print(f"  {_PASS} passed, {_FAIL} failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
