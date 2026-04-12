"""Checkpointer setup — MongoDBSaver for graph state persistence.

The checkpointer stores the full AgentState (including the messages list) per
session_id (used as LangGraph's thread_id). This gives us:
  - In-session memory (the messages list survives across .invoke() calls)
  - Cross-session persistence (conversations survive server restarts)

Observability/evaluation is handled separately by LangSmith (see .env).
"""

import logging
from contextlib import contextmanager
from typing import Iterator

from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from mgr4smb.config import settings
from mgr4smb.exceptions import MongoDBError

logger = logging.getLogger(__name__)

_mongo_client: MongoClient | None = None


def _get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(settings.mongodb_atlas_uri)
            # Fail fast if the cluster is unreachable
            _mongo_client.admin.command("ping")
            logger.info("Memory MongoClient connected")
        except Exception as e:
            logger.error("Memory MongoDB connection failed", exc_info=True)
            raise MongoDBError(f"Could not connect to memory MongoDB: {e}") from e
    return _mongo_client


@contextmanager
def checkpointer_context() -> Iterator[MongoDBSaver]:
    """Yield a MongoDBSaver wired to settings.mongodb_memory_db / _collection.

    Usage:
        with checkpointer_context() as cp:
            graph = workflow.compile(checkpointer=cp)
            graph.invoke(...)

    This is a context manager because MongoDBSaver manages pooled resources.
    """
    client = _get_mongo_client()
    try:
        saver = MongoDBSaver(
            client=client,
            db_name=settings.mongodb_memory_db,
            collection_name=settings.mongodb_memory_collection,
        )
        logger.info(
            "MongoDBSaver initialised db=%s collection=%s",
            settings.mongodb_memory_db,
            settings.mongodb_memory_collection,
        )
        yield saver
    except Exception as e:
        logger.error("MongoDBSaver initialisation failed", exc_info=True)
        raise MongoDBError(f"Could not initialise checkpointer: {e}") from e
