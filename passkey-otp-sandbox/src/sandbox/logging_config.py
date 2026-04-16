"""Structured logging setup. Call setup_logging() once at startup.

Writes to stderr + logs/sandbox.log (rotating). Human-friendly format by
default; pass json_output=True to emit JSON lines.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc"] = self.formatException(record.exc_info)
        for key in ("tool", "agent", "session_id", "status", "email"):
            v = getattr(record, key, None)
            if v is not None:
                entry[key] = v
        return json.dumps(entry, default=str)


class _HumanFormatter(logging.Formatter):
    FMT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = []
        for key in ("tool", "agent", "session_id", "status"):
            v = getattr(record, key, None)
            if v is not None:
                extras.append(f"{key}={v}")
        if extras:
            base += "  " + " ".join(extras)
        return base


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_dir: str | None = None,
) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter = _JSONFormatter() if json_output else _HumanFormatter()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    if log_dir is None:
        log_dir = os.path.join(Path(__file__).resolve().parent.parent.parent, "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "sandbox.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised level=%s json=%s log_dir=%s", level, json_output, log_dir
    )
