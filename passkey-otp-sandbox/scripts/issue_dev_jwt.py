"""Mint a dev JWT for the sandbox.

Usage:
    source .venv/bin/activate
    python scripts/issue_dev_jwt.py          # uses DEV_CLIENT_ID from .env
    python scripts/issue_dev_jwt.py --days 7 # override expiry
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    from sandbox.auth import issue_token
    from sandbox.config import settings

    token = issue_token(client_id=settings.dev_client_id, expires_in_days=args.days)
    print(token)
    print(f"\n# client_id={settings.dev_client_id}  expires_in_days={args.days}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
