"""
End-to-end verification of every Jobber tool shipped with mgr4smb.

Coverage:
  READ tools  (4)  — exercised live against the real account.
                     Pass an --email whose Jobber client has at least one
                     property / job / visit to get full coverage.
                     Default: davidarago99@gmail.com (our dev account).
  WRITE tools (3)  — verified via GraphQL schema introspection. We inspect
                     that the mutation (clientCreate / propertyCreate /
                     jobCreate) exists on Jobber and that the input fields
                     our tool sends are all valid on the input type.
                     We DO NOT actually create any client/property/job —
                     this keeps the live account clean.
  STUB        (1)  — jobber_send_message is a documented NOT-IMPLEMENTED
                     placeholder; we confirm it returns the expected
                     "not yet implemented" message without hitting Jobber.

Usage:
    source .venv/bin/activate
    python scripts/verify_all_jobber_tools.py
    python scripts/verify_all_jobber_tools.py --email other-client@example.com
"""

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.logging_config import setup_logging  # noqa: E402


_PASS = 0
_FAIL = 0
_SKIP = 0


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
        mark = "\033[32m[PASS]\033[0m"
    else:
        _FAIL += 1
        mark = "\033[31m[FAIL]\033[0m"
    msg = f"  {mark} {label}"
    if detail:
        msg += f"\n           {detail}"
    print(msg)


def skip(label: str, reason: str) -> None:
    global _SKIP
    _SKIP += 1
    print(f"  \033[33m[SKIP]\033[0m {label} — {reason}")


# ---------------------------------------------------------------------------
# READ-tool checks (live)
# ---------------------------------------------------------------------------

def check_read_tools(email: str) -> None:
    section(f"Read tools (live — against {email})")

    # --- jobber_get_clients ---
    try:
        from mgr4smb.tools.jobber_get_clients import jobber_get_clients
        result = jobber_get_clients.invoke({"search_value": email})
        ids = re.findall(r"ID:\s*([A-Za-z0-9+/=]{12,})", result)
        check(
            "jobber_get_clients returns a client for the email",
            bool(ids),
            f"first line: {result.splitlines()[0] if result else '(empty)'}",
        )
    except Exception as e:
        check("jobber_get_clients runs", False, f"{type(e).__name__}: {e}")
        ids = []

    if not ids:
        skip("jobber_get_properties / get_jobs / get_visits",
             "no client ID to test against")
        return

    client_id = ids[0]

    # --- jobber_get_properties ---
    try:
        from mgr4smb.tools.jobber_get_properties import jobber_get_properties
        result = jobber_get_properties.invoke({"client_id_jobber": client_id})
        ok = "Jobber API error" not in result and "Error" not in result.splitlines()[0]
        check(
            "jobber_get_properties returns data (no API error)",
            ok,
            result.splitlines()[0] if not ok else "",
        )
    except Exception as e:
        check("jobber_get_properties runs", False, f"{type(e).__name__}: {e}")

    # --- jobber_get_jobs ---
    try:
        from mgr4smb.tools.jobber_get_jobs import jobber_get_jobs
        result = jobber_get_jobs.invoke({"client_id_jobber": client_id})
        ok = "Jobber API error" not in result and "Error" not in result.splitlines()[0]
        check(
            "jobber_get_jobs returns data (no API error)",
            ok,
            result.splitlines()[0] if not ok else "",
        )
    except Exception as e:
        check("jobber_get_jobs runs", False, f"{type(e).__name__}: {e}")

    # --- jobber_get_visits ---
    try:
        from mgr4smb.tools.jobber_get_visits import jobber_get_visits
        result = jobber_get_visits.invoke({"client_id_jobber": client_id})
        ok = "Jobber API error" not in result and "Error" not in result.splitlines()[0]
        check(
            "jobber_get_visits returns data (no API error)",
            ok,
            result.splitlines()[0] if not ok else "",
        )
    except Exception as e:
        check("jobber_get_visits runs", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# WRITE-tool checks (schema introspection — no data mutation)
# ---------------------------------------------------------------------------

_INTROSPECTION_QUERY = """
query VerifyMutationInput($name: String!) {
  __type(name: $name) {
    name
    inputFields {
      name
      type { kind name ofType { name kind } }
    }
  }
}
"""


def _get_input_fields(type_name: str) -> set[str] | None:
    """Return the set of input field names on a Jobber input type, or
    None if the type doesn't exist (or the call fails)."""
    from mgr4smb.tools.jobber_client import execute
    data = execute(_INTROSPECTION_QUERY, {"name": type_name})
    t = (data.get("data") or {}).get("__type")
    if not t:
        return None
    return {f["name"] for f in (t.get("inputFields") or [])}


def check_write_tools() -> None:
    section("Write tools (schema introspection — no live mutations)")

    # Each entry lists the specific Jobber input type(s) our tool depends on
    # AND the field names our tool actually sends on each type. Any drift in
    # the Jobber schema (or in our tool) will surface as a concrete
    # "missing fields" failure here.
    checks: list[tuple[str, list[tuple[str, set[str]]]]] = [
        (
            "jobber_create_client",
            [
                ("ClientCreateInput",
                 {"firstName", "lastName", "companyName", "emails", "phones"}),
                ("EmailCreateAttributes",
                 {"address", "primary", "description"}),
                ("PhoneNumberCreateAttributes",
                 {"number", "primary", "description"}),
            ],
        ),
        (
            "jobber_create_property",
            [
                # propertyCreate takes clientId as a TOP-LEVEL mutation arg
                # and an input of this shape:
                ("PropertyCreateInput", {"properties"}),
                # ... where `properties` points to PropertyAttributes:
                ("PropertyAttributes", {"address", "name"}),
                # ... and the address goes into AddressAttributes:
                ("AddressAttributes",
                 {"street1", "city", "province", "postalCode", "country"}),
            ],
        ),
        (
            "jobber_create_job",
            [
                ("JobCreateAttributes",
                 {"propertyId", "title", "instructions", "timeframe"}),
                ("TimeframeAttributes", {"startAt"}),
            ],
        ),
    ]

    for tool_name, groups in checks:
        for input_type, expected_fields in groups:
            try:
                actual = _get_input_fields(input_type)
            except Exception as e:
                check(
                    f"{tool_name}: introspect {input_type}",
                    False,
                    f"{type(e).__name__}: {e}",
                )
                continue

            if actual is None:
                check(
                    f"{tool_name}: Jobber schema has type {input_type}",
                    False,
                    f"Jobber returned no __type for {input_type}. Did the "
                    "mutation name or input type change on Jobber's side?",
                )
                continue

            missing = expected_fields - actual
            check(
                f"{tool_name}: fields on {input_type}",
                not missing,
                (
                    f"Fields we send that Jobber doesn't accept: {sorted(missing)}\n"
                    f"           Jobber's actual input fields: {sorted(actual)}"
                    if missing
                    else f"checked fields: {sorted(expected_fields)}"
                ),
            )


# ---------------------------------------------------------------------------
# STUB check (no Jobber call)
# ---------------------------------------------------------------------------

def check_stub() -> None:
    section("Placeholder tool (no Jobber call)")

    try:
        from mgr4smb.tools.jobber_send_message import jobber_send_message
    except Exception as e:
        check("jobber_send_message imports", False, f"{type(e).__name__}: {e}")
        return

    try:
        result = jobber_send_message.invoke(
            {"job_id_jobber": "TEST", "message": "hello"}
        )
    except Exception as e:
        check("jobber_send_message runs", False, f"{type(e).__name__}: {e}")
        return

    check(
        "jobber_send_message returns the documented not-implemented message",
        "not yet implemented" in result.lower(),
        f"got: {result[:120]!r}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify every Jobber tool works (reads live, writes via schema)."
    )
    parser.add_argument(
        "--email",
        default="davidarago99@gmail.com",
        help="Email of a known Jobber client (used for read-tool coverage).",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")

    print(_line("═"))
    print("  Jobber tools — full verification")
    print(_line("═"))

    check_read_tools(args.email)
    check_write_tools()
    check_stub()

    print()
    print(_line("═"))
    total = _PASS + _FAIL + _SKIP
    if _FAIL == 0:
        print(f"  All {_PASS} live/schema checks passed. {_SKIP} skipped ({total} total).")
        return 0
    print(f"  {_PASS} passed, {_FAIL} failed, {_SKIP} skipped ({total} total).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
