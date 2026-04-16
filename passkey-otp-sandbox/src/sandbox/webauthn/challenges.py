"""In-memory challenge cache with TTL.

WebAuthn requires the server to remember the exact challenge it issued so
it can be compared byte-for-byte during the finish step. Each challenge
carries the user_email it was issued for and whether it's a registration
or authentication challenge, so we can enforce the user-email match and
dispatch to the right verification path later.

Single-process only. The sandbox is ephemeral — when the server restarts,
pending challenges are lost and the browser has to start over.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Literal

from sandbox.config import settings

Mode = Literal["register", "authenticate"]


class _Entry:
    __slots__ = ("challenge", "user_email", "mode", "created_at")

    def __init__(self, challenge: bytes, user_email: str, mode: Mode) -> None:
        self.challenge = challenge
        self.user_email = user_email
        self.mode = mode
        self.created_at = time.time()


_lock = threading.Lock()
_store: dict[str, _Entry] = {}


def put(challenge: bytes, user_email: str, mode: Mode) -> str:
    """Store a challenge and return its opaque challenge_id."""
    cid = uuid.uuid4().hex
    with _lock:
        _store[cid] = _Entry(challenge, user_email, mode)
    return cid


def pop(challenge_id: str, expected_mode: Mode) -> _Entry:
    """Return and remove the entry, enforcing TTL and mode match."""
    with _lock:
        entry = _store.pop(challenge_id, None)
    if entry is None:
        raise KeyError("unknown or already-consumed challenge_id")
    if time.time() - entry.created_at > settings.challenge_ttl_seconds:
        raise TimeoutError("challenge expired")
    if entry.mode != expected_mode:
        raise ValueError(f"challenge mode mismatch (expected {expected_mode})")
    return entry


def _reset_all_for_tests() -> None:
    with _lock:
        _store.clear()
