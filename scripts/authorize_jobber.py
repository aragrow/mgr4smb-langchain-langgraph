"""
Step 1 of Jobber OAuth — build the authorize URL and open it in the browser.

Paired with scripts/bootstrap_jobber_tokens.py (which handles steps 5 + 6).
Together they cover the full one-time bootstrap:

    authorize_jobber.py          → opens the authorize URL in your browser
        (you grant access; browser redirects to http://localhost:8765/callback
         with ?code=... ; the page fails to load, which is expected)
    (copy the `code=` from the URL bar)
    bootstrap_jobber_tokens.py   → exchanges the code for tokens and
                                   writes .tokens.json

Usage:
    source .venv/bin/activate
    python scripts/authorize_jobber.py

    # If you registered a different redirect URI, pass it here so the
    # URL we build matches (authorize and token exchange must agree):
    python scripts/authorize_jobber.py \\
        --redirect-uri http://localhost:9000/jobber-callback

    # Just print, don't launch the browser (useful over SSH):
    python scripts/authorize_jobber.py --no-launch

The script reads JOBBER_CLIENT_ID from .env via mgr4smb.config.settings.
Never touches or logs JOBBER_CLIENT_SECRET — the secret is only needed
for the token-exchange step, which bootstrap_jobber_tokens.py handles.
"""

import argparse
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.config import settings  # noqa: E402
from mgr4smb.logging_config import setup_logging  # noqa: E402


JOBBER_AUTHORIZE_URL = "https://api.getjobber.com/api/oauth/authorize"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"


def _line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and open the Jobber OAuth authorize URL."
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help=f"Must EXACTLY match a redirect URI registered in your Jobber "
        f"app (scheme + host + port + path). Default: {DEFAULT_REDIRECT_URI}",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Don't try to open the URL in the default browser — just print it.",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")

    # Pre-flight: client_id from .env
    try:
        client_id = settings.jobber_client_id
    except Exception as e:
        print(f"\n✗ Could not read JOBBER_CLIENT_ID from .env: {e}")
        return 1

    # A fresh state value per invocation — Jobber echoes it back on the
    # redirect and we use it to guard against CSRF. For a one-time
    # manual bootstrap the risk is low, but including `state` is always
    # the right pattern.
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    url = f"{JOBBER_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print(_line("═"))
    print("  Jobber OAuth — authorize step (step 1 of 2)")
    print(_line("═"))
    print()
    print(f"  Client ID       ...{client_id[-4:]}")
    print(f"  Redirect URI    {args.redirect_uri}")
    print(f"  State           {state}")
    print()
    print("  Authorize URL:")
    print(f"    {url}")
    print()

    opened = False
    if not args.no_launch:
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False

    if opened:
        print("  ✓ Opened in your default browser.")
    else:
        print("  ! Could not launch a browser automatically — paste the URL")
        print("    above into your browser manually.")

    print()
    print(_line("─"))
    print("  What to do next")
    print(_line("─"))
    print()
    print("  1. In the browser that just opened (or the one you pasted the URL")
    print("     into), sign in to Jobber and click Allow / Authorize.")
    print()
    print("  2. The browser will redirect to a URL that looks like:")
    print(f"       {args.redirect_uri}?code=<LONG_STRING>&state={state}")
    print("     The page will say 'This site can't be reached' — that's")
    print("     expected; no server needs to actually run at that URL.")
    print()
    print("  3. Copy EITHER the entire redirect URL (easier — the next")
    print("     script can extract the code) OR just the `code=` value.")
    print()
    print("  4. Run:")
    print("       python scripts/bootstrap_jobber_tokens.py")
    print("     and paste what you copied when it prompts for the code.")
    print()
    print(f"     If you used a custom --redirect-uri here, pass the same")
    print("     value to bootstrap_jobber_tokens.py so Jobber's token")
    print("     exchange accepts it:")
    print(f"       python scripts/bootstrap_jobber_tokens.py \\")
    print(f"           --redirect-uri {args.redirect_uri}")
    print()
    print(f"  Tip: verify the returned `state` matches {state} before you")
    print("       trust the code.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
