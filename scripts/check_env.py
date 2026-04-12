"""
Phase 1 sanity check — standalone script (runs before package exists).

Usage: python scripts/check_env.py
"""

import sys
import os


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)
    return ok


def main() -> int:
    print("Phase 1 — Environment sanity check\n")
    all_ok = True

    # Python version
    v = sys.version_info
    all_ok &= check(
        f"Python >= 3.10 (found {v.major}.{v.minor}.{v.micro})",
        (v.major, v.minor) >= (3, 10),
    )

    # .venv active
    in_venv = sys.prefix != sys.base_prefix
    all_ok &= check(".venv is activated", in_venv, "run: source .venv/bin/activate")

    # Required packages
    packages = [
        ("langchain", "langchain"),
        ("langchain-core", "langchain_core"),
        ("langchain-google-genai", "langchain_google_genai"),
        ("langgraph", "langgraph"),
        ("langchain-mongodb", "langchain_mongodb"),
        ("pymongo", "pymongo"),
        ("httpx", "httpx"),
        ("python-dotenv", "dotenv"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pyjwt", "jwt"),
    ]
    for pkg_name, import_name in packages:
        try:
            __import__(import_name)
            all_ok &= check(f"Import {pkg_name}", True)
        except ImportError as e:
            all_ok &= check(f"Import {pkg_name}", False, str(e))

    # .env file
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.normpath(env_path)
    env_exists = os.path.isfile(env_path)
    all_ok &= check(f".env file exists at {env_path}", env_exists)

    if env_exists:
        from dotenv import dotenv_values

        env = dotenv_values(env_path)

        required_keys = [
            "GOOGLE_API_KEY",
            "GHL_API_KEY",
            "GHL_LOCATION_ID",
            "GHL_CALENDAR_ID",
            "MONGODB_ATLAS_URI",
            "JOBBER_CLIENT_ID",
            "JOBBER_CLIENT_SECRET",
            "JWT_SECRET",
        ]
        for key in required_keys:
            val = env.get(key, "")
            all_ok &= check(f".env key {key} is set", bool(val), "empty or missing")

        # LangSmith vars
        ls_tracing = env.get("LANGCHAIN_TRACING_V2", "")
        all_ok &= check(
            "LANGCHAIN_TRACING_V2=true",
            ls_tracing.lower() == "true",
            f"found '{ls_tracing}'",
        )
        ls_key = env.get("LANGCHAIN_API_KEY", "")
        all_ok &= check("LANGCHAIN_API_KEY is set", bool(ls_key), "empty or missing")

    # Summary
    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("Some checks FAILED — fix them before proceeding to Phase 2.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
