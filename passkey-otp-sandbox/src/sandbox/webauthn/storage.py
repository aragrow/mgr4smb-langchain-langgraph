"""Passkey credential storage — MongoDB Atlas.

One document per (user_email, credential_id) in the configured passkey
collection. A unique compound index on those two fields is created on
first init_db().

Requires MONGODB_ATLAS_URI to be set in .env — the sandbox no longer
supports a local SQLite fallback for passkey storage.

Public API (unchanged from the previous dual-backend version so callers
don't need to adapt):
    init_db()
    register(email, credential_id, public_key, sign_counter,
             transports=None, aaguid=None, label=None)
    list_by_email(email) -> list[dict]
    find(email, credential_id) -> dict | None
    bump_counter(email, credential_id, new_counter)
    remove(email, credential_id) -> int
    count_for(email) -> int

Returned dicts include: user_email, credential_id, public_key (bytes),
sign_counter (int), transports, aaguid, label, created_at, last_used_at.
`public_key` is always bytes — BSON Binary is normalised before return.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sandbox.config import settings
from sandbox.exceptions import ConfigError

logger = logging.getLogger(__name__)


_mongo_collection = None  # type: ignore[assignment]
_mongo_init_done = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_mongo() -> None:
    if not settings.use_mongodb:
        raise ConfigError(
            "Passkey storage requires MONGODB_ATLAS_URI to be set in .env. "
            "The sandbox no longer supports a local SQLite passkey store."
        )


def _coll():
    """Lazily resolve and cache the passkey collection."""
    global _mongo_collection
    _require_mongo()
    if _mongo_collection is None:
        from sandbox.memory import _get_mongo_client  # lazy; avoids circular

        client = _get_mongo_client()
        _mongo_collection = client[settings.mongodb_passkey_db][
            settings.mongodb_passkey_collection
        ]
        logger.info(
            "passkey store: MongoDB db=%s collection=%s",
            settings.mongodb_passkey_db,
            settings.mongodb_passkey_collection,
        )
    return _mongo_collection


def init_db() -> None:
    """Ensure the unique compound index on (user_email, credential_id).

    Idempotent. Mongo ignores re-creation of an existing index with the
    same spec, so it's safe to call on every request.
    """
    global _mongo_init_done
    if _mongo_init_done:
        return
    coll = _coll()
    coll.create_index(
        [("user_email", 1), ("credential_id", 1)],
        name="user_email_credential_id",
        unique=True,
    )
    coll.create_index([("user_email", 1)], name="user_email")
    _mongo_init_done = True
    logger.debug("Mongo passkey collection indexes ensured")


def _doc_to_dict(d: dict) -> dict:
    """Normalise a Mongo doc to the public shape (bytes for public_key, etc.)."""
    pk = d.get("public_key")
    # BSON Binary subtype 0 arrives as `bson.binary.Binary` which subclasses
    # bytes, so this usually just works — force bytes for safety.
    if pk is not None and not isinstance(pk, bytes):
        pk = bytes(pk)
    return {
        "user_email": d.get("user_email"),
        "credential_id": d.get("credential_id"),
        "public_key": pk,
        "sign_counter": int(d.get("sign_counter", 0)),
        "transports": d.get("transports"),
        "aaguid": d.get("aaguid"),
        "label": d.get("label"),
        "created_at": d.get("created_at"),
        "last_used_at": d.get("last_used_at"),
    }


# --- CRUD -------------------------------------------------------------------


def register(
    email: str,
    credential_id: str,
    public_key: bytes,
    sign_counter: int = 0,
    transports: str | None = None,
    aaguid: str | None = None,
    label: str | None = None,
) -> None:
    init_db()
    doc = {
        "user_email": email,
        "credential_id": credential_id,
        "public_key": bytes(public_key),
        "sign_counter": int(sign_counter),
        "transports": transports,
        "aaguid": aaguid,
        "label": label,
        "created_at": _now(),
        "last_used_at": None,
    }
    # INSERT OR REPLACE semantics — upsert by the unique (email, cred_id) key.
    _coll().replace_one(
        {"user_email": email, "credential_id": credential_id},
        doc,
        upsert=True,
    )


def list_by_email(email: str) -> list[dict[str, Any]]:
    init_db()
    cursor = _coll().find({"user_email": email}, sort=[("created_at", 1)])
    return [_doc_to_dict(d) for d in cursor]


def find(email: str, credential_id: str) -> dict[str, Any] | None:
    init_db()
    d = _coll().find_one({"user_email": email, "credential_id": credential_id})
    return _doc_to_dict(d) if d else None


def bump_counter(email: str, credential_id: str, new_counter: int) -> None:
    init_db()
    _coll().update_one(
        {"user_email": email, "credential_id": credential_id},
        {"$set": {"sign_counter": int(new_counter), "last_used_at": _now()}},
    )


def remove(email: str, credential_id: str) -> int:
    init_db()
    result = _coll().delete_one(
        {"user_email": email, "credential_id": credential_id}
    )
    return int(result.deleted_count)


def count_for(email: str) -> int:
    init_db()
    return int(_coll().count_documents({"user_email": email}))


def _reset_for_tests() -> None:
    """Drop the cached collection handle so the next call rebuilds it."""
    global _mongo_collection, _mongo_init_done
    _mongo_collection = None
    _mongo_init_done = False
