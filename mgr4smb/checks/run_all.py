"""
Cumulative sanity runner — runs every phase gate in order.

Usage:
    python -m mgr4smb.checks.run_all                  # run all 10 phases (default)
    python -m mgr4smb.checks.run_all --up-to 5        # run phases 1..5
    python -m mgr4smb.checks.run_all --fast           # skip live LLM/API checks

--fast mode:
    - phase3/phase4 use --dry-run
    - phase7 uses --structural-only
    - phase8 uses --structural
    - phase9 uses --structural
    - phase10 is skipped (it's always "live")

Use --fast for quick CI-style regression checks; drop it for a full run.
"""

import argparse
import subprocess
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent


# Phase registry: (phase_num, label, command-as-list, fast-command-as-list)
# Fast-command falls back to full command when there is no cheaper variant.
_PHASES: list[tuple[int, str, list[str], list[str]]] = [
    (
        1,
        "Phase 1 — Environment",
        [sys.executable, str(_project_root / "scripts" / "check_env.py")],
        [sys.executable, str(_project_root / "scripts" / "check_env.py")],
    ),
    (
        2,
        "Phase 2 — Skeleton",
        [sys.executable, "-m", "mgr4smb.checks.phase2_skeleton"],
        [sys.executable, "-m", "mgr4smb.checks.phase2_skeleton"],
    ),
    (
        3,
        "Phase 3 — GHL tools",
        [sys.executable, "-m", "mgr4smb.checks.phase3_ghl", "--live"],
        [sys.executable, "-m", "mgr4smb.checks.phase3_ghl", "--dry-run"],
    ),
    (
        4,
        "Phase 4 — Jobber tools",
        [sys.executable, "-m", "mgr4smb.checks.phase4_jobber", "--live"],
        [sys.executable, "-m", "mgr4smb.checks.phase4_jobber", "--dry-run"],
    ),
    (
        5,
        "Phase 5 — MongoDB knowledge base",
        [sys.executable, "-m", "mgr4smb.checks.phase5_mongodb"],
        [sys.executable, "-m", "mgr4smb.checks.phase5_mongodb"],
    ),
    (
        6,
        "Phase 6 — Agent prompts",
        [sys.executable, "-m", "mgr4smb.checks.phase6_prompts"],
        [sys.executable, "-m", "mgr4smb.checks.phase6_prompts"],
    ),
    (
        7,
        "Phase 7 — Agent nodes",
        [sys.executable, "-m", "mgr4smb.checks.phase7_agents"],
        [sys.executable, "-m", "mgr4smb.checks.phase7_agents", "--structural-only"],
    ),
    (
        8,
        "Phase 8 — Full graph",
        [sys.executable, "-m", "mgr4smb.checks.phase8_graph"],
        [sys.executable, "-m", "mgr4smb.checks.phase8_graph", "--structural"],
    ),
    (
        9,
        "Phase 9 — API + auth + menu.sh",
        [sys.executable, "-m", "mgr4smb.checks.phase9_api"],
        [sys.executable, "-m", "mgr4smb.checks.phase9_api", "--structural"],
    ),
    (
        10,
        "Phase 10 — End-to-end integration",
        [sys.executable, "-m", "mgr4smb.checks.phase10_full"],
        None,  # no fast variant — Phase 10 is inherently live
    ),
]


def run_phase(num: int, label: str, cmd: list[str]) -> tuple[bool, str]:
    """Run a single phase gate. Returns (ok, summary_line)."""
    print(f"\n{'='*72}")  # noqa: T201
    print(f"▸ {label}")  # noqa: T201
    print(f"  $ {' '.join(cmd)}")  # noqa: T201
    print(f"{'='*72}")  # noqa: T201

    try:
        result = subprocess.run(cmd, cwd=_project_root)
    except FileNotFoundError as e:
        return False, f"Phase {num:>2}: [FAIL]  (cmd not found: {e})"

    ok = result.returncode == 0
    mark = "[PASS]" if ok else "[FAIL]"
    return ok, f"Phase {num:>2}: {mark}  {label}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cumulative sanity runner")
    parser.add_argument("--up-to", type=int, default=10, help="Run phases 1..N (default 10)")
    parser.add_argument("--fast", action="store_true", help="Skip live API/LLM checks where possible")
    args = parser.parse_args()

    summaries: list[str] = []
    overall_ok = True

    for num, label, full_cmd, fast_cmd in _PHASES:
        if num > args.up_to:
            break

        cmd = fast_cmd if (args.fast and fast_cmd is not None) else full_cmd
        if cmd is None:
            print(f"\nSkipping {label} (no --fast variant)")  # noqa: T201
            continue

        ok, summary = run_phase(num, label, cmd)
        summaries.append(summary)
        if not ok:
            overall_ok = False
            if num < args.up_to:
                print(f"\n  !! Phase {num} failed — stopping before running later phases.")  # noqa: T201
                break

    print(f"\n{'='*72}")  # noqa: T201
    print("Summary")  # noqa: T201
    print(f"{'='*72}")  # noqa: T201
    for s in summaries:
        print(s)  # noqa: T201
    print()  # noqa: T201

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
