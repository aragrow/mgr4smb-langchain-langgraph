"""Structured logging setup — call setup_logging() once at startup.

Outputs to:
  - stderr (always — for uvicorn / terminal / container logs)
  - logs/mgr4smb.log (rotating file — 10 MB max, 5 backups)

Usage in any module:
    import logging
    logger = logging.getLogger(__name__)
"""

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line (for production)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exc"] = self.formatException(record.exc_info)
        for key in ("tool", "agent", "session_id", "status", "service", "email"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val
        return json.dumps(log_entry, default=str)


class _HumanFormatter(logging.Formatter):
    """Human-readable format for development."""

    FMT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = []
        for key in ("tool", "agent", "session_id", "status", "service"):
            val = getattr(record, key, None)
            if val is not None:
                extras.append(f"{key}={val}")
        if extras:
            base += "  " + " ".join(extras)
        return base


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_dir: str | None = None,
) -> None:
    """Configure the root logger. Call once at startup.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, emit JSON lines (production). Otherwise human-readable.
        log_dir: Directory for the rotating log file. Defaults to <project_root>/logs.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers (avoids duplicates on re-init)
    root.handlers.clear()

    formatter = _JSONFormatter() if json_output else _HumanFormatter()

    # stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # Rotating file handler
    if log_dir is None:
        log_dir = os.path.join(Path(__file__).resolve().parent.parent, "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "mgr4smb.log"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised level=%s json=%s log_dir=%s", level, json_output, log_dir
    )
