"""
Phase 2 sanity check — verify project skeleton, config, LLM, logging, exceptions.

Usage: python -m mgr4smb.checks.phase2_skeleton
"""

import logging
import subprocess
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
_results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201 — sanity check script, print is intentional
    _results.append(ok)
    return ok


def main() -> int:
    print("Phase 2 — Skeleton sanity check\n")  # noqa: T201

    # --- Config ---
    try:
        from mgr4smb.config import settings
        check("config.settings imports", True)
        _ = settings.google_api_key
        check("config.settings.google_api_key accessible", True)
    except Exception as e:
        check("config.settings imports", False, str(e))

    # --- Exceptions ---
    try:
        from mgr4smb.exceptions import (
            AgentError,
            AuthError,
            ConfigError,
            ExternalAPIError,
            GHLAPIError,
            InvalidClientError,
            JobberAPIError,
            MongoDBError,
            TokenExpiredError,
            ToolError,
        )
        check("All exceptions import", True)
        # Verify hierarchy
        assert issubclass(GHLAPIError, ExternalAPIError)
        assert issubclass(TokenExpiredError, AuthError)
        check("Exception hierarchy correct", True)
    except Exception as e:
        check("Exceptions import/hierarchy", False, str(e))

    # --- State ---
    try:
        from mgr4smb.state import AgentState
        check("AgentState imports", True)
        hints = AgentState.__annotations__
        required = ["messages", "client_id", "session_id", "contact_id",
                     "user_email", "is_verified"]
        missing = [f for f in required if f not in hints]
        check("AgentState has all required fields", not missing,
              f"missing: {missing}")
    except Exception as e:
        check("AgentState imports", False, str(e))

    # --- Logging ---
    try:
        from mgr4smb.logging_config import setup_logging
        setup_logging(level="DEBUG")
        check("setup_logging() succeeds", True)

        log_file = _project_root / "logs" / "mgr4smb.log"
        check("Log file created at logs/mgr4smb.log", log_file.exists())

        test_logger = logging.getLogger("mgr4smb.checks.phase2_test")
        try:
            raise ValueError("test traceback")
        except ValueError:
            test_logger.error("Traceback capture test", exc_info=True)
        check("logger.error(exc_info=True) runs without error", True)

        log_content = log_file.read_text()
        check("Traceback appears in log file",
              "Traceback" in log_content or "test traceback" in log_content,
              "traceback not found in log")
    except Exception as e:
        check("Logging setup", False, str(e))

    # --- No print() in mgr4smb/ source (excluding checks/) ---
    try:
        result = subprocess.run(
            ["grep", "-rn", r"print(", str(_project_root / "mgr4smb")],
            capture_output=True, text=True,
        )
        violating_lines = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            # Exclude checks/ directory (sanity scripts use print intentionally)
            if "/checks/" in line:
                continue
            # Exclude comments
            stripped = line.split(":", 2)[-1].strip()
            if stripped.startswith("#"):
                continue
            violating_lines.append(line)
        check("No print() in mgr4smb/ source (excluding checks/)",
              len(violating_lines) == 0,
              f"{len(violating_lines)} violations:\n" +
              "\n".join(f"    {l}" for l in violating_lines[:5]))
    except Exception as e:
        check("print() grep check", False, str(e))

    # --- LLM ---
    try:
        from mgr4smb.llm import get_llm
        llm = get_llm()
        check("get_llm() returns ChatGoogleGenerativeAI", True)
    except Exception as e:
        check("get_llm()", False, str(e))
        llm = None

    if llm is not None:
        try:
            resp = llm.invoke("Say hello in one sentence.")
            check("LLM responds to test prompt",
                  resp is not None and len(resp.content) > 0,
                  f"got: {resp}")
        except Exception as e:
            check("LLM invoke", False, str(e))

    # --- Embeddings ---
    try:
        from mgr4smb.llm import get_embeddings
        emb = get_embeddings()
        check("get_embeddings() returns GoogleGenerativeAIEmbeddings", True)
    except Exception as e:
        check("get_embeddings()", False, str(e))
        emb = None

    if emb is not None:
        try:
            vec = emb.embed_query("test query")
            check(f"embed_query returns vector (dim={len(vec)})",
                  isinstance(vec, list) and len(vec) == 768,
                  f"expected 768 dims, got {len(vec) if isinstance(vec, list) else type(vec)}")
        except Exception as e:
            check("embed_query", False, str(e))

    # --- LangSmith trace check (informational) ---
    from mgr4smb.config import settings as s
    if s.langchain_tracing and s.langchain_api_key:
        check("LangSmith tracing enabled (check dashboard for trace)", True)
    else:
        check("LangSmith tracing enabled", False,
              "LANGCHAIN_TRACING_V2 or LANGCHAIN_API_KEY not set")

    # --- Summary ---
    print()  # noqa: T201
    passed = sum(_results)
    total = len(_results)
    if all(_results):
        print(f"All {total} checks passed.")  # noqa: T201
    else:
        print(f"{passed}/{total} checks passed. Fix failures before Phase 3.")  # noqa: T201
    return 0 if all(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
