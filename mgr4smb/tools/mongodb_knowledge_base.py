"""MongoDB Knowledge Base — vector similarity search on the company knowledge base.

Used by GENERAL_INFO_AGENT to answer company questions (hours, services,
pricing, policies, FAQs).

Collection: settings.mongodb_collection (default: knowledge_base) in
settings.mongodb_db_name (default: aragrow-llc). Vector index name:
settings.mongodb_index_name. 768-dim cosine similarity — matches the
embeddings from mgr4smb.llm.get_embeddings().
"""

import logging

from langchain_core.tools import tool
from langchain_mongodb import MongoDBAtlasVectorSearch
from pymongo import MongoClient

from mgr4smb.config import settings
from mgr4smb.exceptions import MongoDBError
from mgr4smb.llm import get_embeddings

logger = logging.getLogger(__name__)

_vector_store: MongoDBAtlasVectorSearch | None = None
_mongo_client: MongoClient | None = None


def _get_vector_store() -> MongoDBAtlasVectorSearch:
    """Return a singleton MongoDBAtlasVectorSearch wired to the knowledge base."""
    global _vector_store, _mongo_client
    if _vector_store is None:
        try:
            _mongo_client = MongoClient(settings.mongodb_atlas_uri)
            collection = _mongo_client[settings.mongodb_db_name][settings.mongodb_collection]
            _vector_store = MongoDBAtlasVectorSearch(
                collection=collection,
                embedding=get_embeddings(),
                index_name=settings.mongodb_index_name,
                relevance_score_fn="cosine",
            )
            logger.info(
                "MongoDB vector store initialised db=%s collection=%s index=%s",
                settings.mongodb_db_name,
                settings.mongodb_collection,
                settings.mongodb_index_name,
            )
        except Exception as e:
            logger.error("MongoDB vector store init failed", exc_info=True)
            raise MongoDBError(f"Failed to initialise MongoDB vector store: {e}") from e
    return _vector_store


@tool
def mongodb_knowledge_base(search_query: str) -> str:
    """Search the company knowledge base for information.

    Use this to answer general questions about the company: services,
    pricing basics, business hours, location, coverage area, policies, FAQs.

    Args:
        search_query: The user's question or topic to search for.
    """
    query = (search_query or "").strip()
    if not query:
        return "Error: A search query is required."

    try:
        store = _get_vector_store()
        # Top-1 result (matches Langflow config number_of_results=1)
        docs = store.similarity_search(query, k=1)
    except MongoDBError:
        raise
    except Exception as e:
        logger.error(
            "mongodb_knowledge_base search failed",
            extra={"tool": "mongodb_knowledge_base"},
            exc_info=True,
        )
        raise MongoDBError(f"Knowledge base search failed: {e}") from e

    if not docs:
        logger.info(
            "No knowledge base match",
            extra={"tool": "mongodb_knowledge_base", "query": query},
        )
        return (
            "No information found in the company knowledge base for that question. "
            "You may want to tell the user we don't have this information on file."
        )

    top = docs[0]
    content = (top.page_content or "").strip()
    logger.info(
        "Knowledge base hit",
        extra={"tool": "mongodb_knowledge_base", "chars": len(content)},
    )
    return content
