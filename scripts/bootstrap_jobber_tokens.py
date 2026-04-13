"""
One-time Jobber OAuth bootstrap — exchange an authorization code for
access + refresh tokens and write them to .tokens.json.

This completes steps 5 and 6 of the manual flow:
  - Step 1-4 happen in YOUR BROWSER. You visit the Jobber authorize URL,
    grant access, read the `code=` query param from the redirect URL in
    the browser's address bar. (A real server at the redirect URI is
    not required — the 'unable to connect' page you see is expected.)
  - This script then asks you for that code, POSTs it to Jobber's token
    endpoint using client_id + client_secret from .env, and writes
    .tokens.json with chmod 600.

Usage:
    source .venv/bin/activate
    python scripts/bootstrap_jobber_tokens.py

    # If you registered a different redirect URI in the Jobber Developer
    # Center, pass it so the token exchange matches:
    python scripts/bootstrap_jobber_tokens.py \\
        --redirect-uri http://localhost:9000/jobber-callback

Pre-conditions:
  - JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET are set in .env.
  - The redirect URI passed here EXACTLY matches one registered on your
    Jobber app (scheme + host + port + path).
  - The code was issued within the last few minutes (Jobber codes are
    short-lived) and has not yet been used.

Safety:
  - Will refuse to overwrite an existing .tokens.json unless you pass
    --force. This prevents accidentally clobbering good tokens mid-debug.
  - Writes the file with 0o600 permissions (owner read/write only).
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx

from mgr4smb.config import settings  # noqa: E402
from mgr4smb.logging_config import setup_logging  # noqa: E402
from mgr4smb.tools.jobber_client import JOBBER_TOKEN_URL  # noqa: E402


DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"


def _line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def _mask(tok: str) -> str:
    """Show only the first 8 and last 4 chars so logs don't leak the token."""
    if not tok or len(tok) < 16:
        return "(too short — possibly empty or malformed)"
    return f"{tok[:8]}…{tok[-4:]}  ({len(tok)} chars)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exchange a Jobber OAuth code for tokens and write .tokens.json",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help=f"Must exactly match the one registered in the Jobber "
        f"Developer Center. Default: {DEFAULT_REDIRECT_URI}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite .tokens.json if it already exists.",
    )
    parser.add_argument(
        "--code",
        default=None,
        help="Skip the prompt and pass the code on the command line (you "
        "probably want the interactive prompt to avoid shell history leaks).",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")

    print(_line("═"))
    print("  Jobber OAuth bootstrap  (steps 5 + 6)")
    print(_line("═"))

    # --- Pre-flight: client creds from .env ---
    try:
        client_id = settings.jobber_client_id
        client_secret = settings.jobber_client_secret
    except Exception as e:
        print(f"\n✗ Could not read Jobber credentials from .env: {e}")
        print("  Make sure JOBBER_CLIENT_ID and JOBBER_CLIENT_SECRET are set.")
        return 1

    print(f"\n  Client ID        ...{client_id[-4:]}")
    print(f"  Redirect URI     {args.redirect_uri}")
    print(f"  Token endpoint   {JOBBER_TOKEN_URL}")
    print(f"  Output file      {settings.jobber_tokens_file}")

    # --- Pre-flight: refuse to clobber without --force ---
    tokens_path: Path = settings.jobber_tokens_file
    if tokens_path.exists() and not args.force:
        print(
            f"\n✗ {tokens_path} already exists. Re-run with --force to "
            "overwrite. (A backup will be written to .tokens.json.bak.)"
        )
        return 1

    # --- Ask for the code ---
    code = (args.code or "").strip()
    if not code:
        print()
        print("  Paste the `code` query parameter from your browser's redirect URL.")
        print("  It's the value between `code=` and the next `&`.")
        try:
            code = input("  code ▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled.")
            return 1

    if not code:
        print("\n✗ No code provided.")
        return 1

    if "code=" in code:
        # user pasted a whole URL or the full query string — salvage it
        # by extracting the first code= value, so they don't have to retry.
        import urllib.parse as _up
        try:
            qs = _up.urlparse(code).query or code
            params = _up.parse_qs(qs)
            if params.get("code"):
                fixed = params["code"][0]
                print(f"  (extracted code from pasted URL: {fixed[:12]}…)")
                code = fixed
        except Exception:
            pass

    # --- POST the token exchange ---
    print()
    print("  Exchanging code for tokens…")
    try:
        resp = httpx.post(
            JOBBER_TOKEN_URL,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": args.redirect_uri,
            },
            headers={"Content-Type": "application/json"},
            timeout=20.0,
        )
    except httpx.HTTPError as e:
        print(f"\n✗ Network error talking to Jobber: {type(e).__name__}: {e}")
        return 1

    if resp.status_code != 200:
        print(f"\n✗ Jobber returned HTTP {resp.status_code}")
        try:
            body = resp.json()
            print(f"  body: {json.dumps(body, indent=2)}")
            err = body.get("error", "")
            if err == "invalid_grant":
                print("\n  invalid_grant usually means:")
                print("   - the code expired (they're only valid for a few minutes)")
                print("   - the code was already used once")
                print("   - the redirect_uri passed here doesn't match what's")
                print("     registered on the Jobber app (must be exact)")
                print("  → Go back to your browser, re-do the authorize step,")
                print("    grab a fresh code, and re-run this script.")
        except Exception:
            print(f"  body (not JSON): {resp.text[:400]}")
        return 1

    payload = resp.json()
    access_token = payload.get("access_token", "")
    refresh_token = payload.get("refresh_token", "")

    if not access_token or not refresh_token:
        print(f"\n✗ Jobber response missing access_token or refresh_token.")
        print(f"  payload keys: {list(payload.keys())}")
        return 1

    print(f"\n  ✓ Received access_token  {_mask(access_token)}")
    print(f"  ✓ Received refresh_token {_mask(refresh_token)}")
    if "expires_in" in payload:
        print(f"  ✓ access_token expires_in {payload['expires_in']} seconds")

    # --- Step 6: write .tokens.json atomically with 0600 perms ---
    if tokens_path.exists() and args.force:
        backup = tokens_path.with_suffix(tokens_path.suffix + ".bak")
        tokens_path.replace(backup)
        print(f"\n  (backed up previous tokens to {backup.name})")

    out = {"access_token": access_token, "refresh_token": refresh_token}
    tmp_path = tokens_path.with_suffix(tokens_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(out, indent=2) + "\n")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(tokens_path)

    print(f"\n  ✓ Wrote {tokens_path}  (mode 0600)")

    # --- Next step suggestion ---
    print()
    print(_line("═"))
    print("  Next: verify connectivity end-to-end")
    print(_line("═"))
    print("    python scripts/test_jobber_connection.py")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
