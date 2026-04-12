"""
Phase 4 sanity check — verify Jobber tools.

Usage:
    python -m mgr4smb.checks.phase4_jobber             # --dry-run (default, no API calls)
    python -m mgr4smb.checks.phase4_jobber --live      # hits real Jobber API
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
    tool_modules = [
        ("jobber_get_clients", "mgr4smb.tools.jobber_get_clients", "jobber_get_clients"),
        ("jobber_get_properties", "mgr4smb.tools.jobber_get_properties", "jobber_get_properties"),
        ("jobber_get_jobs", "mgr4smb.tools.jobber_get_jobs", "jobber_get_jobs"),
        ("jobber_get_visits", "mgr4smb.tools.jobber_get_visits", "jobber_get_visits"),
        ("jobber_create_client", "mgr4smb.tools.jobber_create_client", "jobber_create_client"),
        ("jobber_create_property", "mgr4smb.tools.jobber_create_property", "jobber_create_property"),
        ("jobber_create_job", "mgr4smb.tools.jobber_create_job", "jobber_create_job"),
        ("jobber_send_message", "mgr4smb.tools.jobber_send_message", "jobber_send_message"),
    ]

    tools = {}
    for name, module_path, func_name in tool_modules:
        try:
            mod = __import__(module_path, fromlist=[func_name])
            fn = getattr(mod, func_name)
            tools[name] = fn
            check(f"Import {name}", True)
        except Exception as e:
            check(f"Import {name}", False, str(e))

    # @tool decorator check
    for name, fn in tools.items():
        has_tool = hasattr(fn, "name") and hasattr(fn, "description")
        check(f"{name} has @tool decorator (name + description)", has_tool)

    # JobberClient imports
    try:
        from mgr4smb.tools.jobber_client import (
            JOBBER_GRAPHQL_URL,
            JOBBER_TOKEN_URL,
            JOBBER_VERSION,
            execute,
            get_client,
        )
        check("JobberClient imports (get_client, execute, constants)", True)
        check(
            "JOBBER_GRAPHQL_URL is correct",
            JOBBER_GRAPHQL_URL == "https://api.getjobber.com/api/graphql",
        )
        check(
            "JOBBER_TOKEN_URL is correct",
            JOBBER_TOKEN_URL == "https://api.getjobber.com/api/oauth/token",
        )
    except Exception as e:
        check("JobberClient imports", False, str(e))

    # Signatures
    sig_checks = {
        "jobber_get_clients": ["search_value"],
        "jobber_get_properties": ["client_id_jobber"],
        "jobber_get_jobs": ["client_id_jobber"],
        "jobber_get_visits": ["client_id_jobber"],
        "jobber_create_client": ["first_name", "last_name", "email", "phone"],
        "jobber_create_property": ["client_id_jobber", "street", "city"],
        "jobber_create_job": ["client_id_jobber", "property_id_jobber", "title"],
        "jobber_send_message": ["job_id_jobber", "message"],
    }
    for name, expected_params in sig_checks.items():
        if name not in tools:
            continue
        fn = tools[name]
        inner = fn.func if hasattr(fn, "func") else fn
        sig = inspect.signature(inner)
        params = list(sig.parameters.keys())
        missing = [p for p in expected_params if p not in params]
        check(
            f"{name} signature has {expected_params}",
            not missing,
            f"missing: {missing}, got: {params}",
        )


def live_checks() -> None:
    """Hit real Jobber API — requires credentials and valid .tokens.json."""
    from mgr4smb.tools.jobber_client import execute
    from mgr4smb.tools.jobber_get_clients import jobber_get_clients

    # Simple GraphQL query to verify auth works
    try:
        data = execute("query { account { name } }", {})
        account = data.get("data", {}).get("account", {})
        check(f"Jobber auth works — account: {account.get('name', 'unknown')}", bool(account))
    except Exception as e:
        check("Jobber auth works", False, str(e))
        return

    # Invoke the tool with a clearly bogus search
    try:
        result = jobber_get_clients.invoke({"search_value": "nonexistent-xyz-123456"})
        check(
            "jobber_get_clients handles unknown search gracefully",
            isinstance(result, str) and ("No clients" in result or "No clients found" in result),
            f"got: {result[:100]}",
        )
    except Exception as e:
        check("jobber_get_clients runs without error", False, str(e))


def main() -> int:
    mode = "--live" if "--live" in sys.argv else "--dry-run"
    print(f"Phase 4 — Jobber Tools sanity check ({mode})\n")  # noqa: T201

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
