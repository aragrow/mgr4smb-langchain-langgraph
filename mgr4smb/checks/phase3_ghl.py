"""
Phase 3 sanity check — verify GHL tools.

Usage:
    python -m mgr4smb.checks.phase3_ghl             # --dry-run (default, no API calls)
    python -m mgr4smb.checks.phase3_ghl --live       # hits real GHL API
"""

import inspect
import sys

from mgr4smb.logging_config import setup_logging

setup_logging(level="WARNING")

_results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201
    _results.append(ok)
    return ok


def dry_run_checks() -> None:
    """Structural checks — no API calls."""

    # Import all tools
    tools = {}
    tool_modules = [
        ("ghl_contact_lookup", "mgr4smb.tools.ghl_contact_lookup", "ghl_contact_lookup"),
        ("ghl_available_slots", "mgr4smb.tools.ghl_available_slots", "ghl_available_slots"),
        ("ghl_book_appointment", "mgr4smb.tools.ghl_book_appointment", "ghl_book_appointment"),
        ("ghl_get_appointments", "mgr4smb.tools.ghl_get_appointments", "ghl_get_appointments"),
        ("ghl_cancel_appointment", "mgr4smb.tools.ghl_cancel_appointment", "ghl_cancel_appointment"),
        ("ghl_send_otp", "mgr4smb.tools.ghl_send_otp", "ghl_send_otp"),
        ("ghl_verify_otp", "mgr4smb.tools.ghl_verify_otp", "ghl_verify_otp"),
    ]

    for name, module_path, func_name in tool_modules:
        try:
            mod = __import__(module_path, fromlist=[func_name])
            fn = getattr(mod, func_name)
            tools[name] = fn
            check(f"Import {name}", True)
        except Exception as e:
            check(f"Import {name}", False, str(e))

    # Verify @tool decorator
    for name, fn in tools.items():
        has_tool = hasattr(fn, "name") and hasattr(fn, "description")
        check(f"{name} has @tool decorator (name + description)", has_tool)

    # Verify GHLClient
    try:
        from mgr4smb.tools.ghl_client import GHL_BASE, get_client, search_contact
        check("GHLClient imports (get_client, search_contact)", True)
        check(
            "GHL_BASE is correct",
            GHL_BASE == "https://services.leadconnectorhq.com",
            f"got {GHL_BASE}",
        )
    except Exception as e:
        check("GHLClient imports", False, str(e))

    # Check function signatures have expected parameters
    sig_checks = {
        "ghl_contact_lookup": ["search_value"],
        "ghl_available_slots": ["contact_identifier", "user_timezone"],
        "ghl_book_appointment": ["contact_identifier", "selected_slot", "service_name"],
        "ghl_get_appointments": ["contact_identifier"],
        "ghl_cancel_appointment": ["event_id", "contact_identifier"],
        "ghl_send_otp": ["contact_email", "contact_phone"],
        "ghl_verify_otp": ["contact_identifier", "otp_code"],
    }
    for name, expected_params in sig_checks.items():
        if name not in tools:
            continue
        fn = tools[name]
        # Get the underlying function from the tool wrapper
        inner = fn.func if hasattr(fn, "func") else fn
        sig = inspect.signature(inner)
        params = list(sig.parameters.keys())
        missing = [p for p in expected_params if p not in params]
        check(
            f"{name} signature has {expected_params}",
            not missing,
            f"missing: {missing}, got: {params}",
        )

    # SSRF check — grep for user input in URL paths
    import pathlib
    tools_dir = pathlib.Path(__file__).resolve().parent.parent / "tools"
    violations = []
    for py_file in tools_dir.glob("ghl_*.py"):
        if py_file.name == "ghl_client.py":
            continue
        content = py_file.read_text()
        # Check for f-string URLs that aren't using the base_url pattern
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Flag direct f-string URL construction with variable interpolation
            if 'f"http' in stripped or "f'http" in stripped:
                violations.append(f"{py_file.name}:{i}: {stripped[:100]}")
    check(
        "No user input interpolated into URLs (no f-string http in tool files)",
        len(violations) == 0,
        "\n    ".join(violations) if violations else "",
    )


def live_checks() -> None:
    """Hit real GHL API — requires credentials."""
    from mgr4smb.tools.ghl_client import get_client, search_contact

    # Test search with a real contact (use a known test email)
    try:
        client = get_client()
        check("GHLClient connects", True)
    except Exception as e:
        check("GHLClient connects", False, str(e))
        return

    # Search for a contact that likely doesn't exist
    try:
        result = search_contact("nonexistent-test-12345@fake.invalid")
        check("search_contact returns None for unknown email", result is None)
    except Exception as e:
        check("search_contact handles unknown email", False, str(e))


def main() -> int:
    mode = "--live" if "--live" in sys.argv else "--dry-run"
    print(f"Phase 3 — GHL Tools sanity check ({mode})\n")  # noqa: T201

    dry_run_checks()

    if mode == "--live":
        print()  # noqa: T201
        print("  --- Live API checks ---")  # noqa: T201
        live_checks()

    print()  # noqa: T201
    passed = sum(_results)
    total = len(_results)
    if all(_results):
        print(f"All {total} checks passed.")  # noqa: T201
    else:
        print(f"{passed}/{total} checks passed.")  # noqa: T201
    return 0 if all(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
