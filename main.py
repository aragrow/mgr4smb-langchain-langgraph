"""Entry points for mgr4smb.

Production (API):
    uvicorn mgr4smb.api:app --host 0.0.0.0 --port 8000

Local development (CLI, bypasses JWT auth):
    python main.py --cli
"""

import argparse
import sys
import uuid


def cli() -> int:
    """Interactive terminal chat loop. Same graph as the API, no auth."""
    from mgr4smb.graph import build_graph, run_turn
    from mgr4smb.logging_config import setup_logging
    from mgr4smb.memory import checkpointer_context

    setup_logging(level="WARNING")
    session_id = str(uuid.uuid4())

    print(f"mgr4smb CLI  (session_id={session_id})")  # noqa: T201
    print("Type 'exit' or 'quit' to end, 'new' for a new session.\n")  # noqa: T201

    with checkpointer_context() as cp:
        graph = build_graph(cp)
        while True:
            try:
                user_input = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()  # noqa: T201
                return 0
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                return 0
            if user_input.lower() == "new":
                session_id = str(uuid.uuid4())
                print(f"  [new session: {session_id}]")  # noqa: T201
                continue

            try:
                reply = run_turn(graph, user_input, session_id=session_id)
            except Exception as e:
                print(f"  [error: {e}]")  # noqa: T201
                continue
            print(f"bot > {reply}\n")  # noqa: T201


def main() -> int:
    parser = argparse.ArgumentParser(description="mgr4smb orchestrator")
    parser.add_argument("--cli", action="store_true", help="Run interactive CLI (no auth)")
    args = parser.parse_args()

    if args.cli:
        return cli()

    parser.print_help()
    print("\nTo start the API server: uvicorn mgr4smb.api:app --host 0.0.0.0 --port 8000")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
