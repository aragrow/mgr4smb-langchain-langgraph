"""
Phase 9 sanity check — verify API, auth, and menu.sh.

Uses FastAPI's TestClient for /chat and /health (no real uvicorn needed),
and subshells menu.sh for the ops commands (create/reissue/revoke/status).

Usage:
    python -m mgr4smb.checks.phase9_api
    python -m mgr4smb.checks.phase9_api --structural   # skip LLM + menu.sh
"""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from mgr4smb.logging_config import setup_logging

setup_logging(level="WARNING")

_project_root = Path(__file__).resolve().parent.parent.parent
_results: list[bool] = []

# Use a separate clients file for tests so we don't pollute the real one
_TEST_CLIENTS_FILE = _project_root / "clients.test.json"


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201
    _results.append(ok)
    return ok


# ---------------------------------------------------------------------------
# Auth & /chat tests via TestClient
# ---------------------------------------------------------------------------

def api_tests() -> None:
    from fastapi.testclient import TestClient

    from mgr4smb.api import app
    from mgr4smb.auth import issue_token

    # Point the auth module at our test clients file for the duration of this check.
    original_file = os.environ.get("CLIENTS_FILE")
    os.environ["CLIENTS_FILE"] = str(_TEST_CLIENTS_FILE)

    # Reset the cached settings property (module-level singleton)
    # Simpler: write test data to the configured path in settings
    from mgr4smb.config import settings
    test_file = settings.clients_file  # uses current env

    test_cid = str(uuid.uuid4())
    disabled_cid = str(uuid.uuid4())
    test_file.write_text(
        json.dumps(
            {
                "clients": [
                    {"client_id": test_cid, "name": "Test Client", "enabled": True,
                     "created_at": "2026-04-12T00:00:00Z"},
                    {"client_id": disabled_cid, "name": "Disabled Client", "enabled": False,
                     "created_at": "2026-04-12T00:00:00Z"},
                ]
            },
            indent=2,
        )
    )
    test_file.chmod(0o600)

    good_token = issue_token(test_cid, expires_in_days=1)
    disabled_token = issue_token(disabled_cid, expires_in_days=1)
    unknown_token = issue_token(str(uuid.uuid4()), expires_in_days=1)
    expired_token = issue_token(test_cid, expires_in_days=-1)  # already expired

    try:
        # Use TestClient which triggers lifespan startup/shutdown
        with TestClient(app) as client:
            check("FastAPI app starts (TestClient lifespan OK)", True)

            # /health
            r = client.get("/health")
            check(f"GET /health returns JSON (status={r.status_code})",
                   r.headers.get("content-type", "").startswith("application/json"))
            health = r.json()
            check(
                "GET /health body has 'status' and 'checks' keys",
                "status" in health and "checks" in health,
                f"got: {health}",
            )
            check(
                "GET /health mongodb check is 'ok'",
                health.get("checks", {}).get("mongodb") == "ok",
                f"got: {health.get('checks', {}).get('mongodb')}",
            )

            # /chat without auth → 401
            r = client.post("/chat", json={"message": "hello"})
            check("POST /chat with missing header → 401", r.status_code == 401,
                  f"got {r.status_code}")

            # /chat with malformed header → 401
            r = client.post("/chat", json={"message": "hello"},
                             headers={"Authorization": "NotBearer xxx"})
            check("POST /chat with malformed header → 401", r.status_code == 401)

            # /chat with bogus signature → 401
            r = client.post("/chat", json={"message": "hello"},
                             headers={"Authorization": "Bearer bogus.token.value"})
            check("POST /chat with invalid token → 401", r.status_code == 401)

            # /chat with unknown client_id → 401
            r = client.post("/chat", json={"message": "hello"},
                             headers={"Authorization": f"Bearer {unknown_token}"})
            check("POST /chat with unknown client_id → 401", r.status_code == 401)

            # /chat with disabled client → 401
            r = client.post("/chat", json={"message": "hello"},
                             headers={"Authorization": f"Bearer {disabled_token}"})
            check("POST /chat with disabled client → 401", r.status_code == 401)

            # /chat with expired token → 401
            r = client.post("/chat", json={"message": "hello"},
                             headers={"Authorization": f"Bearer {expired_token}"})
            check("POST /chat with expired token → 401", r.status_code == 401)

            # No sub-agent endpoints
            for bad_path in ("/greeting", "/booking", "/otp"):
                r = client.post(bad_path, json={})
                check(f"POST {bad_path} → 404 (no sub-agent endpoints)", r.status_code == 404)

            # Happy path: valid JWT
            r = client.post(
                "/chat",
                json={"message": "My email is test-auth@example.com and phone is +15551234567. "
                                   "What are your hours?"},
                headers={"Authorization": f"Bearer {good_token}"},
            )
            check(f"POST /chat with valid JWT → 200 (got {r.status_code})",
                   r.status_code == 200, f"body: {r.text[:200]}")
            if r.status_code == 200:
                body = r.json()
                check("POST /chat response has 'response' + 'session_id'",
                       "response" in body and "session_id" in body,
                       f"keys: {list(body.keys())}")
                check("POST /chat returns a new UUID session_id when none provided",
                       len(body.get("session_id", "")) == 36)

                # Session continuity: same session_id on turn 2
                sid = body["session_id"]
                r2 = client.post(
                    "/chat",
                    json={"message": "Just checking — am I still connected?",
                           "session_id": sid},
                    headers={"Authorization": f"Bearer {good_token}"},
                )
                check(f"POST /chat with session_id → 200 (got {r2.status_code})",
                       r2.status_code == 200)
                if r2.status_code == 200:
                    check("Turn 2 returns same session_id",
                           r2.json().get("session_id") == sid)

    finally:
        # Cleanup test clients file
        try:
            test_file.unlink()
        except FileNotFoundError:
            pass
        if original_file is None:
            os.environ.pop("CLIENTS_FILE", None)
        else:
            os.environ["CLIENTS_FILE"] = original_file


# ---------------------------------------------------------------------------
# menu.sh structural tests (we don't start a real server — that would conflict
# with running uvicorn). We verify the script exists, is executable, and
# the help / status paths run.
# ---------------------------------------------------------------------------

def menu_tests() -> None:
    menu = _project_root / "menu.sh"
    check("menu.sh exists at project root", menu.exists())
    check("menu.sh is executable", menu.stat().st_mode & 0o111)

    content = menu.read_text()
    for option in (
        "Start server",
        "Stop server",
        "Restart server",
        "Server status",
        "Create new client",
        "List clients",
        "Reissue JWT",
        "Revoke client",
    ):
        check(f"menu.sh has menu option: {option}", option in content)

    # Status sub-command: we can run the status function via a short stdin feed.
    # The status command doesn't touch state; it's safe to invoke.
    # We pipe "4\n9\n" to select status then exit.
    try:
        result = subprocess.run(
            ["bash", str(menu)],
            input="4\n9\n",
            capture_output=True,
            text=True,
            timeout=20,
        )
        combined = result.stdout + result.stderr
        check(
            "menu.sh option 4 (status) runs without error",
            result.returncode == 0,
            f"rc={result.returncode}, output: {combined[:300]}",
        )
        check(
            "menu.sh status output mentions 'running' or 'not running'",
            "running" in combined.lower(),
        )
    except Exception as e:
        check("menu.sh status invocation", False, str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("Phase 9 — API + auth + menu.sh sanity check\n")  # noqa: T201

    if "--structural" in sys.argv:
        # Structural-only: verify imports and menu.sh layout without starting the app
        try:
            from mgr4smb import api, auth  # noqa: F401
            check("Import mgr4smb.api + mgr4smb.auth", True)
        except Exception as e:
            check("Import mgr4smb.api + mgr4smb.auth", False, str(e))

        menu_tests()
    else:
        print("API + auth (via FastAPI TestClient):")  # noqa: T201
        api_tests()

        print("\nmenu.sh:")  # noqa: T201
        menu_tests()

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
