"""Checkpointer factory — MongoDB when configured, in-memory otherwise.

The LangGraph checkpointer stores the full AgentState per session_id
(used as LangGraph's thread_id), giving us:
  - In-session memory (messages survive across .invoke() calls)
  - Cross-session persistence (conversations survive server restarts)
    — ONLY when using MongoDB. The in-memory saver is per-process.

Usage (from api.py's lifespan):

    with checkpointer_context() as cp:
        graph = build_graph(cp)
        ...

Both branches are context managers so callers use one interface.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from langgraph.checkpoint.memory import InMemorySaver

from sandbox.config import settings
from sandbox.exceptions import SandboxError

logger = logging.getLogger(__name__)


_mongo_client = None  # type: ignore  # pymongo.MongoClient when set


def _get_mongo_client():
    """Lazy-construct + cache a MongoClient. Pings the cluster to fail fast."""
    global _mongo_client
    if _mongo_client is None:
        try:
            from pymongo import MongoClient  # imported lazily

            _mongo_client = MongoClient(settings.mongodb_atlas_uri)
            _mongo_client.admin.command("ping")
            logger.info("MongoClient connected")
        except Exception as e:
            raise SandboxError(f"Could not connect to MongoDB: {e}") from e
    return _mongo_client


@contextmanager
def checkpointer_context() -> Iterator[object]:
    """Yield a LangGraph checkpointer — MongoDBSaver or InMemorySaver.

    The branch is chosen from settings.use_mongodb (i.e. whether
    MONGODB_ATLAS_URI is set in .env).
    """
    if settings.use_mongodb:
        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver

            client = _get_mongo_client()
            saver = MongoDBSaver(
                client=client,
                db_name=settings.mongodb_memory_db,
                collection_name=settings.mongodb_checkpoint_collection,
            )
            logger.info(
                "checkpointer: MongoDBSaver db=%s collection=%s",
                settings.mongodb_memory_db,
                settings.mongodb_checkpoint_collection,
            )
            yield saver
            return
        except Exception as e:
            raise SandboxError(f"Could not initialise MongoDB checkpointer: {e}") from e

    saver = InMemorySaver()
    logger.info("checkpointer: InMemorySaver (MONGODB_ATLAS_URI not set)")
    yield saver
