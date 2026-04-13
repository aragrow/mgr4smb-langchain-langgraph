"""
Replay the failing conversation from session 22e348a2 against the live graph.

Verifies the phone-normalization fix (commit 8bc7c4e): on the original session
OTP rejected '9522281752' against the stored '+19522281752'. With the fix,
the same conversation should reach OTP_SENT, after which you type the
6-digit code from your inbox to complete the booking.

Usage:
    source .venv/bin/activate
    python scripts/replay_session_22e348a2.py

    # Auto-stop right before the OTP step (good for an automated smoke check):
    python scripts/replay_session_22e348a2.py --stop-before-otp

    # Use a custom email / phone:
    python scripts/replay_session_22e348a2.py --email me@example.com --phone 9525551212

The script talks to the graph in-process (same Python, no HTTP, no JWT).
"""

import argparse
import sys
import textwrap
import uuid
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mgr4smb.graph import build_graph, run_turn  # noqa: E402
from mgr4smb.logging_config import setup_logging  # noqa: E402
from mgr4smb.memory import checkpointer_context  # noqa: E402


# ---------------------------------------------------------------------------
# Pretty IO
# ---------------------------------------------------------------------------

def _line(ch: str = "─", n: int = 78) -> str:
    return ch * n


def _print_user(msg: str) -> None:
    print(f"\n{_line('─')}")
    print(f"USER  ▶ {msg}")


def _print_agent(reply: str) -> None:
    print(f"AGENT ◀\n{textwrap.indent(reply.strip(), '         ')}\n")


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay session 22e348a2 to verify the OTP phone-normalization fix"
    )
    parser.add_argument("--email", default="davidarago99@gmail.com")
    parser.add_argument("--phone", default="9522281752")
    parser.add_argument(
        "--stop-before-otp",
        action="store_true",
        help="Halt right before the slot selection (no OTP email triggered).",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Use a specific session_id (default: a new UUID).",
    )
    args = parser.parse_args()

    setup_logging(level="WARNING")
    sid = args.session_id or f"replay-{uuid.uuid4()}"

    print(_line("═"))
    print(f"  Replay of session 22e348a2  →  new session_id: {sid}")
    print(f"  email: {args.email}")
    print(f"  phone: {args.phone}")
    print(_line("═"))

    # Pre-OTP turns from the original session
    pre_otp_turns = [
        "Hi, I need help with my WordPress site.",
        args.email,
        args.phone,
        "I need to optimize my website performance, a SEO Audit, and an AEO audit.",
        "quick appointment",
        "Central",
        "America/Chicago",
    ]

    with checkpointer_context() as cp:
        graph = build_graph(cp)

        # --- Walk through the pre-OTP conversation ---
        for turn_msg in pre_otp_turns:
            _print_user(turn_msg)
            try:
                reply = run_turn(graph, turn_msg, session_id=sid, client_id="replay")
            except Exception as e:
                print(f"  ✗ Error: {type(e).__name__}: {e}")
                return 1
            _print_agent(reply)

        # --- Slot selection & OTP step ---
        if args.stop_before_otp:
            print(_line("═"))
            print("  Stopped before OTP (per --stop-before-otp).")
            print("  At this point the agent should have offered slots and be waiting")
            print("  for your selection. The OTP fix has NOT been exercised yet.")
            print(_line("═"))
            return 0

        print(_line("═"))
        print("  Above this line: agent should have offered numbered slots.")
        print("  Type the slot NUMBER (e.g. '1', '2', '3', '4') to trigger OTP.")
        print(_line("═"))
        slot_choice = input("Slot number ▶ ").strip() or "1"

        _print_user(slot_choice)
        try:
            reply = run_turn(graph, slot_choice, session_id=sid, client_id="replay")
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")
            return 1
        _print_agent(reply)

        # If the agent asked for an OTP code, pause for it
        if "code" in reply.lower() or "verification" in reply.lower():
            print(_line("═"))
            print("  Agent has asked for a verification code.")
            print("  Check the inbox for the email above for a 6-digit code,")
            print("  then paste it below. (Press Enter without typing to skip.)")
            print(_line("═"))
            otp_code = input("OTP code ▶ ").strip()
            if otp_code:
                _print_user(otp_code)
                try:
                    reply = run_turn(graph, otp_code, session_id=sid, client_id="replay")
                except Exception as e:
                    print(f"  ✗ Error: {type(e).__name__}: {e}")
                    return 1
                _print_agent(reply)
            else:
                print("  (Skipping OTP entry — booking will not be finalized.)")

    print(_line("═"))
    print(f"  Replay complete. session_id: {sid}")
    print(f"  In LangSmith, filter by:  tags has \"session:{sid}\"")
    print(_line("═"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
