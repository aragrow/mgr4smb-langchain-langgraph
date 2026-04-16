"""Knowledge base tool — dual backend (MongoDB when configured, local JSON otherwise).

Contract mirrors mgr4smb's `mongodb_knowledge_base`:
    @tool knowledge_base(search_query: str) -> str
returns the best-matching passage from the company KB as plain text, or
a graceful "no information" message when nothing is found.

Backend selection is driven by settings.use_mongodb (i.e. whether
MONGODB_ATLAS_URI is set in .env):

- **MongoDB mode** — MongoDBAtlasVectorSearch on the configured db +
  collection + vector index. Top-1 via similarity_search(query, k=1).
  Identical to production. Use scripts/ingest_kb_to_mongo.py to populate
  the collection from knowledge_base.json.

- **Local mode** — corpus is read from knowledge_base.json at the
  sandbox root. Embeddings are computed on first use and cached to
  .kb_embeddings.json (gitignored). Cosine similarity is pure Python —
  no numpy. Entries are embedded as `topic + content` so short
  conceptual queries rank well.

Both modes use the same Gemini embedder (see sandbox.llm.get_embeddings),
so vectors are interchangeable — you can copy the cache directly into
MongoDB via the ingest script without re-embedding.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from langchain_core.tools import tool

from sandbox.config import PROJECT_ROOT, settings
from sandbox.exceptions import SandboxError
from sandbox.llm import get_embeddings

logger = logging.getLogger(__name__)


_KB_FILE: Path = PROJECT_ROOT / "knowledge_base.json"
_CACHE_FILE: Path = PROJECT_ROOT / ".kb_embeddings.json"

_vectors: list[dict] | None = None
_mongo_vector_store = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Local-mode helpers
# ---------------------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_corpus() -> list[dict]:
    if not _KB_FILE.exists():
        return []
    try:
        data = json.loads(_KB_FILE.read_text())
    except json.JSONDecodeError as e:
        raise SandboxError(f"knowledge_base.json is not valid JSON: {e}") from e
    entries = data.get("entries", [])
    return [e for e in entries if e.get("content")]


def _cache_is_fresh() -> bool:
    if not (_CACHE_FILE.exists() and _KB_FILE.exists()):
        return False
    return _CACHE_FILE.stat().st_mtime >= _KB_FILE.stat().st_mtime


def _load_cache() -> list[dict] | None:
    if not _cache_is_fresh():
        return None
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return None


def _save_cache(vectors: list[dict]) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(vectors))
        _CACHE_FILE.chmod(0o600)
    except Exception as e:
        logger.warning("could not write embedding cache: %s", e)


def _build_vectors() -> list[dict]:
    """Lazy-build the embedded corpus (cached to disk)."""
    global _vectors
    if _vectors is not None:
        return _vectors

    cached = _load_cache()
    if cached is not None:
        logger.info("loaded %d KB vectors from cache", len(cached))
        _vectors = cached
        return _vectors

    corpus = _load_corpus()
    if not corpus:
        logger.warning("knowledge base is empty (%s)", _KB_FILE)
        _vectors = []
        return _vectors

    logger.info("embedding %d knowledge base entries (first use)", len(corpus))
    embeddings = get_embeddings()
    # Embed `topic + content` so the topic words reinforce the retrieval
    # signal. On 768-dim Gemini embeddings, short conceptual queries
    # otherwise produce noisy rankings across medium-length passages.
    texts = [
        f"{e.get('topic', '').strip()}\n\n{e['content']}" if e.get("topic")
        else e["content"]
        for e in corpus
    ]
    vecs = embeddings.embed_documents(texts)
    built = [
        {"topic": e.get("topic", ""), "content": e["content"], "vector": v}
        for e, v in zip(corpus, vecs)
    ]
    _save_cache(built)
    _vectors = built
    return _vectors


def _search_local(query: str) -> str:
    try:
        vectors = _build_vectors()
    except SandboxError as e:
        logger.error("knowledge_base (local) init failed: %s", e)
        return f"Error: {e}"

    if not vectors:
        return (
            "No information found in the company knowledge base for that question. "
            "Tell the user we don't have this information on file."
        )

    try:
        q_vec = get_embeddings().embed_query(query)
    except Exception as e:
        logger.error("query embedding failed", exc_info=True)
        return f"Error: knowledge base query embedding failed: {e}"

    scored = [(_cosine(q_vec, v["vector"]), v) for v in vectors]
    best_score, best = max(scored, key=lambda t: t[0])
    logger.info(
        "knowledge_base hit (local)",
        extra={
            "tool": "knowledge_base",
            "backend": "local",
            "topic": best.get("topic", ""),
            "score": round(best_score, 3),
            "chars": len(best.get("content", "")),
        },
    )
    return best["content"]


# ---------------------------------------------------------------------------
# MongoDB-mode helpers
# ---------------------------------------------------------------------------

def _get_mongo_vector_store():
    """Return a singleton MongoDBAtlasVectorSearch (imported lazily)."""
    global _mongo_vector_store
    if _mongo_vector_store is not None:
        return _mongo_vector_store
    try:
        from langchain_mongodb import MongoDBAtlasVectorSearch

        from sandbox.memory import _get_mongo_client

        client = _get_mongo_client()
        collection = client[settings.mongodb_db_name][settings.mongodb_kb_collection]
        _mongo_vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=get_embeddings(),
            index_name=settings.mongodb_kb_index_name,
            relevance_score_fn="cosine",
        )
        logger.info(
            "MongoDB vector store initialised db=%s collection=%s index=%s",
            settings.mongodb_db_name,
            settings.mongodb_kb_collection,
            settings.mongodb_kb_index_name,
        )
        return _mongo_vector_store
    except Exception as e:
        raise SandboxError(f"Could not initialise MongoDB vector store: {e}") from e


def _search_mongo(query: str) -> str:
    try:
        store = _get_mongo_vector_store()
        docs = store.similarity_search(query, k=1)
    except SandboxError as e:
        logger.error("knowledge_base (mongo) failed: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.error("mongo similarity_search failed", exc_info=True)
        return f"Error: knowledge base search failed: {e}"

    if not docs:
        return (
            "No information found in the company knowledge base for that question. "
            "Tell the user we don't have this information on file."
        )

    top = docs[0]
    content = (top.page_content or "").strip()
    logger.info(
        "knowledge_base hit (mongo)",
        extra={"tool": "knowledge_base", "backend": "mongo", "chars": len(content)},
    )
    return content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _reset_for_tests() -> None:
    """Drop the in-memory caches so the next call rebuilds (used by smoke)."""
    global _vectors, _mongo_vector_store
    _vectors = None
    _mongo_vector_store = None


@tool
def knowledge_base(search_query: str) -> str:
    """Search the company knowledge base for information.

    Use this to answer general questions about the company: services,
    pricing basics, business hours, location, coverage area, policies, FAQs.

    Args:
        search_query: The user's question or topic to search for.
    """
    query = (search_query or "").strip()
    if not query:
        return "Error: A search query is required."

    if settings.use_mongodb:
        return _search_mongo(query)
    return _search_local(query)
